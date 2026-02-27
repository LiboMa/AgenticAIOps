"""Tests for kubernetes skill loading via SkillLoader."""

from __future__ import annotations

import pytest
from pathlib import Path

from src.aci.skills import SkillLoader, SafetyTier


SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


@pytest.fixture
def loader():
    return SkillLoader(SKILLS_DIR)


class TestKubernetesSkillDiscovery:
    """Test that kubernetes skill is discovered correctly."""

    def test_discover_finds_kubernetes(self, loader):
        summaries = loader.discover()
        names = [s.name for s in summaries]
        assert "kubernetes" in names

    def test_discover_finds_linux_admin(self, loader):
        summaries = loader.discover()
        names = [s.name for s in summaries]
        assert "linux-admin" in names

    def test_summary_has_description(self, loader):
        summaries = loader.discover()
        k8s = next(s for s in summaries if s.name == "kubernetes")
        assert "CKA" in k8s.description
        assert "Kubernetes" in k8s.description


class TestKubernetesSkillLoad:
    """Test full load of kubernetes skill."""

    def test_load_name(self, loader):
        k8s = loader.load("kubernetes")
        assert k8s.name == "kubernetes"

    def test_load_safety_tier(self, loader):
        k8s = loader.load("kubernetes")
        assert k8s.safety.tier == SafetyTier.GUARDED

    def test_load_requires_approval(self, loader):
        k8s = loader.load("kubernetes")
        assert "delete" in k8s.safety.requires_approval
        assert "drain" in k8s.safety.requires_approval
        assert "cordon" in k8s.safety.requires_approval

    def test_load_instructions_not_empty(self, loader):
        k8s = loader.load("kubernetes")
        assert len(k8s.instructions) > 500
        assert "CKA-level" in k8s.instructions

    def test_load_references(self, loader):
        k8s = loader.load("kubernetes")
        refs = k8s.list_references()
        assert "TROUBLESHOOT.md" in refs
        assert "DANGEROUS_OPS.md" in refs

    def test_load_reference_content(self, loader):
        k8s = loader.load("kubernetes")
        content = k8s.get_reference("TROUBLESHOOT.md")
        assert content is not None
        assert "CrashLoopBackOff" in content

    def test_load_missing_reference_returns_none(self, loader):
        k8s = loader.load("kubernetes")
        assert k8s.get_reference("NONEXISTENT.md") is None


class TestKubernetesSkillTools:
    """Test kubernetes skill tool discovery."""

    def test_tools_loaded(self, loader):
        k8s = loader.load("kubernetes")
        tools = k8s.get_tools()
        assert len(tools) >= 15  # at least 15 tools expected

    def test_read_tools_present(self, loader):
        k8s = loader.load("kubernetes")
        tool_names = {t.tool_name for t in k8s.get_tools()}
        expected_read = {
            "get_pods", "describe_resource", "get_events",
            "kubectl_logs", "get_nodes", "top_pods", "top_nodes",
            "rollout_status", "get_resource_yaml", "check_endpoints",
        }
        assert expected_read.issubset(tool_names), \
            f"Missing read tools: {expected_read - tool_names}"

    def test_write_tools_present(self, loader):
        k8s = loader.load("kubernetes")
        tool_names = {t.tool_name for t in k8s.get_tools()}
        expected_write = {
            "scale_resource", "rollout_restart", "rollout_undo",
            "label_resource", "apply_manifest", "patch_resource",
        }
        assert expected_write.issubset(tool_names), \
            f"Missing write tools: {expected_write - tool_names}"

    def test_dangerous_tools_present(self, loader):
        k8s = loader.load("kubernetes")
        tool_names = {t.tool_name for t in k8s.get_tools()}
        expected_dangerous = {
            "delete_resource", "drain_node", "cordon_node", "uncordon_node",
        }
        assert expected_dangerous.issubset(tool_names), \
            f"Missing dangerous tools: {expected_dangerous - tool_names}"

    def test_tools_are_strands_decorated(self, loader):
        k8s = loader.load("kubernetes")
        for t in k8s.get_tools():
            assert hasattr(t, "tool_name"), f"{t} missing tool_name"
            assert hasattr(t, "tool_spec"), f"{t} missing tool_spec"

    def test_tool_specs_have_descriptions(self, loader):
        k8s = loader.load("kubernetes")
        for t in k8s.get_tools():
            spec = t.tool_spec
            assert spec.get("description"), \
                f"Tool {t.tool_name} has no description"

    def test_no_duplicate_tool_names(self, loader):
        k8s = loader.load("kubernetes")
        names = [t.tool_name for t in k8s.get_tools()]
        assert len(names) == len(set(names)), \
            f"Duplicate tool names: {[n for n in names if names.count(n) > 1]}"


class TestSkillLoaderCaching:
    """Test that SkillLoader caches properly."""

    def test_load_returns_cached(self, loader):
        k8s1 = loader.load("kubernetes")
        k8s2 = loader.load("kubernetes")
        assert k8s1 is k8s2

    def test_load_all_includes_both_skills(self, loader):
        all_skills = loader.load_all()
        names = {s.name for s in all_skills}
        assert "kubernetes" in names
        assert "linux-admin" in names


class TestGetAgentTools:
    """Test the multi-skill tool aggregation."""

    def test_get_agent_tools_dedupes(self, loader):
        k8s = loader.load("kubernetes")
        la = loader.load("linux-admin")
        combined = SkillLoader.get_agent_tools(k8s, la)
        names = [t.tool_name for t in combined]
        assert len(names) == len(set(names))

    def test_get_agent_tools_merges(self, loader):
        k8s = loader.load("kubernetes")
        la = loader.load("linux-admin")
        combined = SkillLoader.get_agent_tools(k8s, la)
        names = {t.tool_name for t in combined}
        assert "get_pods" in names
        assert "system_overview" in names
