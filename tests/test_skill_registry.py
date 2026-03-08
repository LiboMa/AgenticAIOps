"""Tests for SkillRegistry (Phase 1 Task 1) — singleton, Pydantic, routing.

Skeleton written by Tester ahead of implementation. Tests will be
activated once Developer delivers src/aci/skills/registry.py.

Test matrix (~44 cases):
  - Registry singleton & lifecycle: 8
  - Pydantic SkillManifest validation: 12
  - can_handle() routing: 10
  - create_isolated() test factory: 6
  - Error paths & edge cases: 8
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml


# ── Helpers ─────────────────────────────────────────────────────


def _make_skill_dir(base, name, *, tier="read-only", description="Test skill",
                    version="0.1.0", domains=None, keywords=None,
                    confidence_boost=0.0, tools_code=None):
    """Create a minimal skill directory for testing."""
    skill = base / name
    skill.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "name": name, "description": description, "version": version,
        "tier": tier,
        "routing": {
            "domains": domains or [name],
            "keywords": keywords or [name],
            "confidence_boost": confidence_boost,
        },
    }
    body = f"---\n{yaml.dump(frontmatter, default_flow_style=False)}---\n\n# {name}\n\nInstructions.\n"
    (skill / "SKILL.md").write_text(body)
    safety_dir = skill / "references" / "safety"
    safety_dir.mkdir(parents=True, exist_ok=True)
    (safety_dir / "safety_tier.yaml").write_text(yaml.dump({"tier": tier}))
    tools_dir = skill / "tools"
    tools_dir.mkdir(exist_ok=True)
    code = tools_code or f'def list_items(ns="default"): return f"items in {{ns}}"'
    (tools_dir / "diagnose.py").write_text(code)
    return skill


@pytest.fixture
def skills_root(tmp_path):
    _make_skill_dir(tmp_path, "kubernetes", tier="guarded",
                    description="Kubernetes cluster operations",
                    domains=["kubernetes", "k8s"],
                    keywords=["pod", "deployment", "kubectl", "namespace"])
    _make_skill_dir(tmp_path, "linux-admin", tier="read-only",
                    description="Linux system diagnostics",
                    domains=["linux"],
                    keywords=["disk", "memory", "process", "log"])
    _make_skill_dir(tmp_path, "aws-cloud", tier="destructive",
                    description="AWS cloud resource management",
                    domains=["aws"],
                    keywords=["ec2", "s3", "lambda", "iam"],
                    confidence_boost=0.1)
    return tmp_path


# ══════════════════════════════════════════════════════════════════
# 1. Registry Singleton & Lifecycle (8 tests)
# ══════════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="Awaiting registry.py implementation")
class TestRegistrySingleton:
    def test_singleton_same_instance(self, skills_root): pass
    def test_singleton_thread_safe(self, skills_root): pass
    def test_discover_returns_all_skills(self, skills_root): pass
    def test_discover_idempotent(self, skills_root): pass
    def test_get_existing_skill(self, skills_root): pass
    def test_get_nonexistent_skill_raises(self, skills_root): pass
    def test_list_summaries_lightweight(self, skills_root): pass
    def test_registry_reset(self, skills_root): pass


# ══════════════════════════════════════════════════════════════════
# 2. Pydantic SkillManifest Validation (12 tests)
# ══════════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="Awaiting registry.py implementation")
class TestSkillManifest:
    def test_valid_manifest_parses(self, skills_root): pass
    def test_missing_name_rejected(self, tmp_path): pass
    def test_missing_description_rejected(self, tmp_path): pass
    def test_empty_description_rejected(self, tmp_path): pass
    def test_description_max_length(self, tmp_path): pass
    def test_confidence_boost_clamped_low(self, tmp_path): pass
    def test_confidence_boost_clamped_high(self, tmp_path): pass
    def test_confidence_boost_valid_range(self, skills_root): pass
    def test_invalid_tier_rejected(self, tmp_path): pass
    def test_malformed_yaml_skipped_with_warning(self, tmp_path):
        _make_skill_dir(tmp_path, "bad-yaml")
        (tmp_path / "bad-yaml" / "SKILL.md").write_text("---\n: invalid: yaml: [[\n---\n")
    def test_missing_skill_md_skipped(self, tmp_path):
        (tmp_path / "no-manifest").mkdir()
    def test_version_defaults(self, skills_root): pass


# ══════════════════════════════════════════════════════════════════
# 3. can_handle() Routing (10 tests)
# ══════════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="Awaiting registry.py implementation")
class TestCanHandle:
    def test_domain_exact_match(self, skills_root): pass
    def test_keyword_match(self, skills_root): pass
    def test_multiple_matches_ranked(self, skills_root): pass
    def test_no_match_returns_empty(self, skills_root): pass
    def test_confidence_boost_applied(self, skills_root): pass
    def test_domain_filter_restricts(self, skills_root): pass
    def test_max_results_respected(self, skills_root): pass
    def test_score_range_0_to_1(self, skills_root): pass
    def test_case_insensitive_matching(self, skills_root): pass
    def test_empty_query_returns_all(self, skills_root): pass


# ══════════════════════════════════════════════════════════════════
# 4. create_isolated() Test Factory (6 tests)
# ══════════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="Awaiting registry.py implementation")
class TestCreateIsolated:
    def test_isolated_is_independent(self, skills_root): pass
    def test_isolated_has_all_skills(self, skills_root): pass
    def test_isolated_no_shared_state(self, skills_root): pass
    def test_isolated_custom_skills_dir(self, tmp_path): pass
    def test_isolated_cleanup(self, skills_root): pass
    def test_isolated_in_parametrize(self, skills_root): pass


# ══════════════════════════════════════════════════════════════════
# 5. Error Paths & Edge Cases (8 tests)
# ══════════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="Awaiting registry.py implementation")
class TestEdgeCases:
    def test_empty_skills_directory(self, tmp_path): pass
    def test_duplicate_skill_names(self, tmp_path): pass
    def test_skill_dir_is_file(self, tmp_path):
        (tmp_path / "not-a-dir.txt").write_text("hello")
    def test_permission_denied_skill(self, tmp_path): pass
    def test_importlib_tool_not_found(self, tmp_path): pass
    def test_tools_dir_missing(self, tmp_path):
        skill = tmp_path / "no-tools"; skill.mkdir()
        (skill / "SKILL.md").write_text("---\nname: no-tools\ndescription: test\n---\n")
    def test_concurrent_discover_safe(self, skills_root): pass
    def test_hot_reload_detects_new_skill(self, skills_root): pass
