"""Integration test: verify all 8 skills can be registered and loaded by agent tier."""

import pytest
import importlib
import inspect
from src.skills import SkillRegistry
from src.skills._models import SecurityTier, SkillManifest


# Collect all tool modules
SKILL_MODULES = {
    "kubernetes": "src.skills.kubernetes.tools",
    "linux_admin": "src.skills.linux_admin.tools",
    "network_engineer": "src.skills.network_engineer.tools",
    "aws_general": "src.skills.aws_general.tools",
    "database_admin": "src.skills.database_admin.tools",
    "monitoring": "src.skills.monitoring.tools",
    "log_analysis": "src.skills.log_analysis.tools",
    "storage": "src.skills.storage.tools",
}


def _get_tools(module_path: str):
    """Import module and return all @secure_tool decorated functions."""
    mod = importlib.import_module(module_path)
    tools = []
    for name, obj in inspect.getmembers(mod):
        if hasattr(obj, "_security_tier") and hasattr(obj, "_tool_name"):
            tools.append(obj)
    return tools


def _manifest(name: str) -> SkillManifest:
    return SkillManifest(name=name, description=f"{name} skill")


class TestAllSkillsRegistration:
    """Verify all 8 skills register successfully."""

    def test_all_skills_register(self):
        reg = SkillRegistry.create_isolated()
        for name, mod_path in SKILL_MODULES.items():
            tools = _get_tools(mod_path)
            assert len(tools) > 0, f"Skill '{name}' has no @secure_tool tools"
            reg.register_skill(name, manifest=_manifest(name), tools=tools)
        assert len(reg.list_skills()) == 8

    def test_total_tool_count(self):
        reg = SkillRegistry.create_isolated()
        total = 0
        for name, mod_path in SKILL_MODULES.items():
            tools = _get_tools(mod_path)
            reg.register_skill(name, manifest=_manifest(name), tools=tools)
            total += len(tools)
        # ADR-006: ~96 tools across 8 skills
        assert total >= 80, f"Expected 80+ tools, got {total}"

    @pytest.mark.parametrize("skill_name,mod_path", SKILL_MODULES.items())
    def test_all_tools_have_secure_decorator(self, skill_name, mod_path):
        """ADR-006 §8.2 invariant: every tool must have @secure_tool."""
        tools = _get_tools(mod_path)
        for tool in tools:
            assert hasattr(tool, "_security_tier"), \
                f"{skill_name}/{tool._tool_name} missing _security_tier"
            assert hasattr(tool, "_skill_name"), \
                f"{skill_name}/{tool._tool_name} missing _skill_name"

    def test_detect_agent_gets_readonly_only(self):
        """Detect agent (T0) should only get read-only tools."""
        reg = SkillRegistry.create_isolated()
        for name, mod_path in SKILL_MODULES.items():
            reg.register_skill(name, manifest=_manifest(name), tools=_get_tools(mod_path))

        tools = reg.load_for_agent("detect", ["ALL"], SecurityTier.T0_READONLY)
        for t in tools:
            assert t._security_tier == SecurityTier.T0_READONLY, \
                f"Detect got non-T0 tool: {t._tool_name} (tier={t._security_tier.name})"

    def test_sre_agent_gets_all_tools(self):
        """SRE agent (T3) gets every tool."""
        reg = SkillRegistry.create_isolated()
        total = 0
        for name, mod_path in SKILL_MODULES.items():
            tools = _get_tools(mod_path)
            reg.register_skill(name, manifest=_manifest(name), tools=tools)
            total += len(tools)

        sre_tools = reg.load_for_agent("sre", ["ALL"], SecurityTier.T3_DESTRUCTIVE)
        assert len(sre_tools) >= total - 5  # cross-skill dedup

    def test_tier_distribution(self):
        """Verify reasonable tier distribution across all skills."""
        tiers = {t: 0 for t in SecurityTier}
        for mod_path in SKILL_MODULES.values():
            for tool in _get_tools(mod_path):
                tiers[tool._security_tier] += 1

        # Most tools should be T0 (read-only)
        total = sum(tiers.values())
        assert tiers[SecurityTier.T0_READONLY] / total >= 0.5, \
            f"T0 should be ≥50% of tools, got {tiers[SecurityTier.T0_READONLY]}/{total}"
        # T3 should be rare
        assert tiers[SecurityTier.T3_DESTRUCTIVE] <= 10, \
            f"Too many T3 tools: {tiers[SecurityTier.T3_DESTRUCTIVE]}"

    @pytest.mark.parametrize("skill_name,mod_path", SKILL_MODULES.items())
    def test_no_duplicate_tool_names_within_skill(self, skill_name, mod_path):
        """Each skill should have unique tool names."""
        tools = _get_tools(mod_path)
        names = [t._tool_name for t in tools]
        assert len(names) == len(set(names)), \
            f"Skill '{skill_name}' has duplicate tool names: {[n for n in names if names.count(n) > 1]}"
