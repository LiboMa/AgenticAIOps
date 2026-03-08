"""Tests for src/skills/__init__.py — SkillRegistry."""

import json
import pytest
from src.skills import SkillRegistry, RegisteredSkill
from src.skills._models import SecurityTier, SkillManifest
from src.skills._security import secure_tool, set_agent_context


# ─── Fixtures ─────────────────────────────────────────────────

@secure_tool(tier=SecurityTier.T0_READONLY, skill="mock", command_param=None)
def mock_read_tool() -> str:
    return json.dumps({"status": "success"})

@secure_tool(tier=SecurityTier.T1_LOW_RISK, skill="mock", command_param=None)
def mock_write_tool() -> str:
    return json.dumps({"status": "success"})

@secure_tool(tier=SecurityTier.T2_HIGH_RISK, skill="mock", command_param=None)
def mock_danger_tool(approval_token: str = "") -> str:
    return json.dumps({"status": "success"})


def _make_manifest(name: str = "test-skill", **kw) -> SkillManifest:
    return SkillManifest(
        name=name,
        description=f"Test skill: {name}",
        keywords=kw.get("keywords", ["test"]),
        domains=kw.get("domains", ["compute"]),
        confidence_boost=kw.get("confidence_boost", 0.0),
    )


class TestSkillRegistrySingleton:
    def setup_method(self):
        SkillRegistry.reset()

    def test_get_returns_singleton(self):
        r1 = SkillRegistry.get()
        r2 = SkillRegistry.get()
        assert r1 is r2

    def test_reset_clears_singleton(self):
        r1 = SkillRegistry.get()
        SkillRegistry.reset()
        r2 = SkillRegistry.get()
        assert r1 is not r2

    def test_create_isolated_not_singleton(self):
        singleton = SkillRegistry.get()
        isolated = SkillRegistry.create_isolated()
        assert singleton is not isolated


class TestSkillRegistration:
    def setup_method(self):
        self.reg = SkillRegistry.create_isolated()

    def test_register_skill(self):
        self.reg.register_skill(
            "k8s", manifest=_make_manifest("k8s"),
            tools=[mock_read_tool, mock_write_tool],
        )
        assert "k8s" in self.reg.list_skills()

    def test_duplicate_name_raises(self):
        self.reg.register_skill(
            "k8s", manifest=_make_manifest("k8s"), tools=[mock_read_tool],
        )
        with pytest.raises(RuntimeError, match="already registered"):
            self.reg.register_skill(
                "k8s", manifest=_make_manifest("k8s"), tools=[mock_write_tool],
            )

    def test_frozen_registry_rejects(self):
        self.reg.freeze()
        with pytest.raises(RuntimeError, match="frozen"):
            self.reg.register_skill(
                "k8s", manifest=_make_manifest("k8s"), tools=[mock_read_tool],
            )

    def test_undecorated_tool_rejected(self):
        def raw_tool():
            pass
        with pytest.raises(ValueError, match="not decorated with @secure_tool"):
            self.reg.register_skill(
                "bad", manifest=_make_manifest("bad"), tools=[raw_tool],
            )

    def test_duplicate_tool_name_rejected(self):
        with pytest.raises(ValueError, match="Duplicate tool name"):
            self.reg.register_skill(
                "dup", manifest=_make_manifest("dup"),
                tools=[mock_read_tool, mock_read_tool],
            )


class TestLoadForAgent:
    def setup_method(self):
        self.reg = SkillRegistry.create_isolated()
        self.reg.register_skill(
            "k8s", manifest=_make_manifest("k8s"),
            tools=[mock_read_tool, mock_write_tool, mock_danger_tool],
        )

    def test_detect_gets_t0_only(self):
        tools = self.reg.load_for_agent("detect", ["k8s"], SecurityTier.T0_READONLY)
        assert len(tools) == 1
        assert tools[0]._tool_name == "mock_read_tool"

    def test_rca_gets_t0_t1(self):
        tools = self.reg.load_for_agent("rca", ["k8s"], SecurityTier.T1_LOW_RISK)
        assert len(tools) == 2
        names = {t._tool_name for t in tools}
        assert names == {"mock_read_tool", "mock_write_tool"}

    def test_sre_gets_all(self):
        tools = self.reg.load_for_agent("sre", ["k8s"], SecurityTier.T2_HIGH_RISK)
        assert len(tools) == 3

    def test_all_keyword(self):
        tools = self.reg.load_for_agent("sre", ["ALL"], SecurityTier.T2_HIGH_RISK)
        assert len(tools) == 3

    def test_unknown_skill_skipped(self):
        tools = self.reg.load_for_agent("detect", ["nonexistent"], SecurityTier.T0_READONLY)
        assert len(tools) == 0


class TestCanHandle:
    def setup_method(self):
        self.reg = SkillRegistry.create_isolated()
        self.reg.register_skill(
            "kubernetes", manifest=_make_manifest(
                "kubernetes",
                keywords=["pod", "kubectl", "deployment", "node", "k8s"],
                domains=["kubernetes", "container"],
                confidence_boost=0.2,
            ),
            tools=[mock_read_tool],
        )
        self.reg.register_skill(
            "linux_admin", manifest=_make_manifest(
                "linux_admin",
                keywords=["process", "disk", "cpu", "memory", "linux"],
                domains=["compute"],
            ),
            tools=[mock_write_tool],
        )

    def test_routes_kubectl_to_kubernetes(self):
        matches = self.reg.can_handle("kubectl get pods is failing")
        assert matches[0] == "kubernetes"

    def test_routes_cpu_to_linux(self):
        matches = self.reg.can_handle("high cpu usage on host")
        assert "linux_admin" in matches

    def test_no_match_returns_empty(self):
        assert self.reg.can_handle("weather forecast") == []


class TestInvariantGateTest:
    """ADR-006 §8.2: All tools must have @secure_tool."""

    def test_all_registered_tools_have_secure_decorator(self):
        reg = SkillRegistry.create_isolated()
        reg.register_skill(
            "k8s", manifest=_make_manifest("k8s"),
            tools=[mock_read_tool, mock_write_tool, mock_danger_tool],
        )
        skill = reg.get_skill("k8s")
        for name, tool_fn in skill.tools.items():
            assert hasattr(tool_fn, "_security_tier"), f"Tool '{name}' missing @secure_tool"
            assert hasattr(tool_fn, "_skill_name"), f"Tool '{name}' missing skill attribution"
