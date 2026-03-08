"""SkillValidator — 5-layer security validation for Harness-generated Skills.

Design: ADR-009 §8.5
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Blocked patterns (ADR-006 security model)
_BLOCKED_CALLS = {
    "os.system", "os.popen", "subprocess.Popen", "subprocess.call",
    "subprocess.run",  # must use ShellExecutor
    "eval", "exec", "__import__",
}

_IMMUTABLE_FILES = {
    "_security.py", "SecurityFilter", "approval_token.py",
}


@dataclass
class SkillDraft:
    """Output from Harness — a draft Skill to validate."""

    domain: str
    skill_md_content: str
    tools_py_content: str
    test_content: str = ""
    output_dir: str = ""


@dataclass
class ValidationResult:
    """Result of 5-layer validation."""

    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    draft: Optional[SkillDraft] = None

    @property
    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {len(self.errors)} errors, {len(self.warnings)} warnings"


class SkillValidator:
    """Validate Harness-generated Skills through 5 security layers.

    Layer 1: AST static scan — blocked calls
    Layer 2: SKILL.md frontmatter compliance
    Layer 3: @secure_tool decorator check
    Layer 4: Tier assignment check (new Skill default T0_READONLY)
    Layer 5: Dry-run import test
    """

    def validate(self, draft: SkillDraft) -> ValidationResult:
        """Run all 5 validation layers.

        Args:
            draft: SkillDraft from Harness output.

        Returns:
            ValidationResult with pass/fail and detailed errors.
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Layer 1: AST static scan
        l1_errors = self._layer1_ast_scan(draft.tools_py_content)
        errors.extend(l1_errors)

        # Layer 2: SKILL.md frontmatter
        l2_errors, l2_warnings = self._layer2_frontmatter(draft.skill_md_content)
        errors.extend(l2_errors)
        warnings.extend(l2_warnings)

        # Layer 3: @secure_tool decorator
        l3_errors = self._layer3_secure_tool(draft.tools_py_content)
        errors.extend(l3_errors)

        # Layer 4: Tier assignment
        l4_errors = self._layer4_tier_check(draft.skill_md_content, draft.tools_py_content)
        errors.extend(l4_errors)

        # Layer 5: Dry-run import
        l5_errors = self._layer5_dry_run(draft.tools_py_content)
        errors.extend(l5_errors)

        result = ValidationResult(
            passed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            draft=draft,
        )
        logger.info("Skill validation %s: %s", result.summary, draft.domain)
        return result

    def _layer1_ast_scan(self, code: str) -> list[str]:
        """Layer 1: AST scan for blocked calls."""
        errors = []
        if not code.strip():
            errors.append("L1: tools.py is empty")
            return errors

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            errors.append(f"L1: SyntaxError in tools.py: {e}")
            return errors

        for node in ast.walk(tree):
            # Check function calls
            if isinstance(node, ast.Call):
                call_name = self._get_call_name(node)
                if call_name in _BLOCKED_CALLS:
                    errors.append(f"L1: Blocked call detected: {call_name} (line {node.lineno})")

            # Check imports of blocked modules used for dangerous calls
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in ("os", "subprocess"):
                        # Not an error by itself, but flag for awareness
                        pass

        return errors

    def _layer2_frontmatter(self, skill_md: str) -> tuple[list[str], list[str]]:
        """Layer 2: Validate SKILL.md frontmatter."""
        errors = []
        warnings = []

        if not skill_md.strip():
            errors.append("L2: SKILL.md is empty")
            return errors, warnings

        # Check for YAML frontmatter
        if not skill_md.strip().startswith("---"):
            errors.append("L2: SKILL.md missing YAML frontmatter (must start with ---)")
            return errors, warnings

        # Extract frontmatter
        parts = skill_md.split("---", 2)
        if len(parts) < 3:
            errors.append("L2: SKILL.md frontmatter not properly closed")
            return errors, warnings

        frontmatter = parts[1]

        # Required fields
        required_fields = ["name", "version"]
        for field_name in required_fields:
            if f"{field_name}:" not in frontmatter:
                errors.append(f"L2: Missing required frontmatter field: {field_name}")

        # Check for tools list
        if "tools:" not in frontmatter:
            warnings.append("L2: No 'tools' field in frontmatter")

        return errors, warnings

    def _layer3_secure_tool(self, code: str) -> list[str]:
        """Layer 3: Check all tool functions have @secure_tool decorator."""
        errors = []
        if not code.strip():
            return errors

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return errors  # Already caught in L1

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                # Check if function has @secure_tool or @tool decorator
                decorator_names = []
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Name):
                        decorator_names.append(dec.id)
                    elif isinstance(dec, ast.Attribute):
                        decorator_names.append(dec.attr)
                    elif isinstance(dec, ast.Call):
                        if isinstance(dec.func, ast.Name):
                            decorator_names.append(dec.func.id)
                        elif isinstance(dec.func, ast.Attribute):
                            decorator_names.append(dec.func.attr)

                if "secure_tool" not in decorator_names and "tool" not in decorator_names:
                    errors.append(
                        f"L3: Function '{node.name}' (line {node.lineno}) missing @secure_tool decorator"
                    )

        return errors

    def _layer4_tier_check(self, skill_md: str, code: str) -> list[str]:
        """Layer 4: New Skills must default to T0_READONLY."""
        errors = []

        # Check for write-like operations without proper tier
        write_patterns = [
            r'\bdelete\b', r'\bremove\b', r'\bkill\b', r'\brestart\b',
            r'\bscale\b', r'\bpatch\b', r'\bapply\b', r'\bexec\b',
        ]

        has_write_ops = any(re.search(p, code, re.IGNORECASE) for p in write_patterns)

        # Check tier in frontmatter
        tier_match = re.search(r'tier:\s*(\S+)', skill_md, re.IGNORECASE)
        tier = tier_match.group(1) if tier_match else "T0_READONLY"

        if has_write_ops and tier.upper() in ("T0_READONLY", "T0"):
            errors.append(
                "L4: Write operations detected but tier is T0_READONLY — "
                "needs manual tier upgrade approval"
            )

        return errors

    def _layer5_dry_run(self, code: str) -> list[str]:
        """Layer 5: Dry-run — check if code can be parsed and compiled."""
        errors = []
        if not code.strip():
            return errors

        try:
            compiled = compile(code, "<skill_draft>", "exec")
            if not compiled:
                errors.append("L5: Compilation returned empty result")
        except SyntaxError as e:
            errors.append(f"L5: Dry-run compile failed: {e}")
        except Exception as e:
            errors.append(f"L5: Unexpected dry-run error: {e}")

        return errors

    @staticmethod
    def _get_call_name(node: ast.Call) -> str:
        """Extract full call name from AST Call node."""
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                return f"{node.func.value.id}.{node.func.attr}"
        return ""
