"""
Tests for src/skills/skill_bridge.py — Skills Bridge L1 integration.
"""
import json
import logging
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

# ---------------------------------------------------------------------------
# Helpers — reset state between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_skill_state():
    """Reset SkillRegistry singleton and bridge state before each test."""
    from src.skills import SkillRegistry
    from src.skills import skill_bridge
    SkillRegistry.reset()
    skill_bridge.reset_bridge()
    yield
    SkillRegistry.reset()
    skill_bridge.reset_bridge()


# ---------------------------------------------------------------------------
# We mock the _discover_tools to avoid importing boto3 / kubectl / etc.
# ---------------------------------------------------------------------------

def _make_fake_tool(name: str, skill: str, tier_value: int, doc: str = "Fake tool"):
    """Create a mock tool function with the right attributes."""
    from src.skills._models import SecurityTier

    def tool_fn(**kwargs):
        from src.skills._models import ToolResult
        return ToolResult.success({"tool": name, "args": kwargs}).to_json()

    tool_fn.__name__ = name
    tool_fn.__doc__ = doc
    tool_fn._tool_name = name
    tool_fn._skill_name = skill
    tool_fn._security_tier = SecurityTier(tier_value)
    return tool_fn


def _fake_discover_tools(module_path: str):
    """Return fake tools based on module path, simulating real discovery."""
    from src.skills._models import SecurityTier

    skill_name = module_path.split(".")[-2]  # e.g. "src.skills.kubernetes.tools" -> "kubernetes"

    # Each skill gets a T0 + T1 + T2 tool
    tools = [
        _make_fake_tool(f"{skill_name}_read", skill_name, 0, f"Read {skill_name} data"),
        _make_fake_tool(f"{skill_name}_action", skill_name, 1, f"Low-risk {skill_name} action"),
        _make_fake_tool(f"{skill_name}_danger", skill_name, 2, f"High-risk {skill_name} action"),
    ]
    return tools


@pytest.fixture
def mock_discover():
    """Patch _discover_tools across all tests."""
    with patch("src.skills.agent_binding._discover_tools", side_effect=_fake_discover_tools):
        yield


# ===========================================================================
# ensure_initialized
# ===========================================================================

class TestEnsureInitialized:

    def test_returns_registry(self, mock_discover):
        from src.skills.skill_bridge import ensure_initialized
        from src.skills import SkillRegistry

        reg = ensure_initialized()
        assert isinstance(reg, SkillRegistry)

    def test_idempotent(self, mock_discover):
        from src.skills.skill_bridge import ensure_initialized

        reg1 = ensure_initialized()
        reg2 = ensure_initialized()
        assert reg1 is reg2

    def test_registers_all_skills(self, mock_discover):
        from src.skills.skill_bridge import ensure_initialized

        reg = ensure_initialized()
        skills = reg.list_skills()
        # 8 skill modules
        assert len(skills) == 8
        assert "kubernetes" in skills
        assert "monitoring" in skills
        assert "log_analysis" in skills

    def test_sets_initialized_flag(self, mock_discover):
        from src.skills import skill_bridge
        assert skill_bridge._initialized is False
        skill_bridge.ensure_initialized()
        assert skill_bridge._initialized is True

    def test_logging(self, mock_discover, caplog):
        from src.skills.skill_bridge import ensure_initialized
        with caplog.at_level(logging.INFO, logger="src.skills.skill_bridge"):
            ensure_initialized()
        assert "Skills framework initialized" in caplog.text


# ===========================================================================
# get_*_tools
# ===========================================================================

class TestGetTools:

    def test_detect_tools_are_callable(self, mock_discover):
        from src.skills.skill_bridge import get_detect_tools
        tools = get_detect_tools()
        assert len(tools) > 0
        assert all(callable(t) for t in tools)

    def test_detect_tools_only_t0(self, mock_discover):
        from src.skills.skill_bridge import get_detect_tools
        from src.skills._models import SecurityTier
        tools = get_detect_tools()
        for t in tools:
            assert t._security_tier <= SecurityTier.T0_READONLY

    def test_rca_tools_include_t1(self, mock_discover):
        from src.skills.skill_bridge import get_rca_tools
        from src.skills._models import SecurityTier
        tools = get_rca_tools()
        tiers = {t._security_tier for t in tools}
        assert SecurityTier.T1_LOW_RISK in tiers

    def test_rca_has_more_tools_than_detect(self, mock_discover):
        from src.skills.skill_bridge import get_detect_tools, get_rca_tools
        detect = get_detect_tools()
        rca = get_rca_tools()
        assert len(rca) > len(detect)

    def test_sre_has_all_tools(self, mock_discover):
        from src.skills.skill_bridge import get_sre_tools, get_rca_tools
        sre = get_sre_tools()
        rca = get_rca_tools()
        assert len(sre) >= len(rca)

    def test_sre_includes_high_risk(self, mock_discover):
        from src.skills.skill_bridge import get_sre_tools
        from src.skills._models import SecurityTier
        tools = get_sre_tools()
        tiers = {t._security_tier for t in tools}
        assert SecurityTier.T2_HIGH_RISK in tiers

    def test_detect_tools_have_tool_name_attr(self, mock_discover):
        from src.skills.skill_bridge import get_detect_tools
        tools = get_detect_tools()
        for t in tools:
            assert hasattr(t, '_tool_name')
            assert isinstance(t._tool_name, str)

    def test_detect_tools_count(self, mock_discover):
        """8 skills × 1 T0 tool each = 8 detect tools."""
        from src.skills.skill_bridge import get_detect_tools
        tools = get_detect_tools()
        assert len(tools) == 8


# ===========================================================================
# get_*_prompt
# ===========================================================================

class TestGetPrompts:

    def test_detect_prompt_nonempty(self, mock_discover):
        from src.skills.skill_bridge import get_detect_prompt
        prompt = get_detect_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_detect_prompt_contains_tool_names(self, mock_discover):
        from src.skills.skill_bridge import get_detect_prompt
        prompt = get_detect_prompt()
        assert "kubernetes_read" in prompt

    def test_rca_prompt_contains_role(self, mock_discover):
        from src.skills.skill_bridge import get_rca_prompt
        prompt = get_rca_prompt()
        assert "rca" in prompt.lower()

    def test_sre_prompt_has_more_tools_than_detect(self, mock_discover):
        from src.skills.skill_bridge import get_detect_prompt, get_sre_prompt
        detect_p = get_detect_prompt()
        sre_p = get_sre_prompt()
        assert len(sre_p) > len(detect_p)

    def test_prompt_mentions_available_skills(self, mock_discover):
        from src.skills.skill_bridge import get_detect_prompt
        prompt = get_detect_prompt()
        assert "Available Skills" in prompt


# ===========================================================================
# execute_skill_tool
# ===========================================================================

class TestExecuteSkillTool:

    def test_valid_tool(self, mock_discover):
        from src.skills.skill_bridge import execute_skill_tool
        result = execute_skill_tool("kubernetes_read", agent_role="detect")
        parsed = json.loads(result)
        assert parsed["status"] == "success"

    def test_invalid_tool_returns_error(self, mock_discover):
        from src.skills.skill_bridge import execute_skill_tool
        result = execute_skill_tool("nonexistent_tool", agent_role="detect")
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "not found" in parsed["error"]

    def test_tool_with_kwargs(self, mock_discover):
        from src.skills.skill_bridge import execute_skill_tool
        result = execute_skill_tool("kubernetes_read", agent_role="detect", namespace="default")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["data"]["args"]["namespace"] == "default"

    def test_tier_enforcement(self, mock_discover):
        """Detect agent should not see T1 tools."""
        from src.skills.skill_bridge import execute_skill_tool
        # kubernetes_action is T1, not available to detect
        result = execute_skill_tool("kubernetes_action", agent_role="detect")
        parsed = json.loads(result)
        assert parsed["status"] == "error"

    def test_rca_can_access_t1(self, mock_discover):
        from src.skills.skill_bridge import execute_skill_tool
        result = execute_skill_tool("kubernetes_action", agent_role="rca")
        parsed = json.loads(result)
        assert parsed["status"] == "success"


# ===========================================================================
# list_available_tools
# ===========================================================================

class TestListAvailableTools:

    def test_returns_list_of_dicts(self, mock_discover):
        from src.skills.skill_bridge import list_available_tools
        tools = list_available_tools("detect")
        assert isinstance(tools, list)
        assert len(tools) > 0
        assert all(isinstance(t, dict) for t in tools)

    def test_dict_keys(self, mock_discover):
        from src.skills.skill_bridge import list_available_tools
        tools = list_available_tools("detect")
        for t in tools:
            assert "name" in t
            assert "skill" in t
            assert "tier" in t
            assert "doc" in t

    def test_tier_is_string(self, mock_discover):
        from src.skills.skill_bridge import list_available_tools
        tools = list_available_tools("detect")
        for t in tools:
            assert isinstance(t["tier"], str)

    def test_sre_has_more_than_detect(self, mock_discover):
        from src.skills.skill_bridge import list_available_tools
        detect_tools = list_available_tools("detect")
        sre_tools = list_available_tools("sre")
        assert len(sre_tools) > len(detect_tools)

    def test_doc_is_string(self, mock_discover):
        from src.skills.skill_bridge import list_available_tools
        tools = list_available_tools("detect")
        for t in tools:
            assert isinstance(t["doc"], str)


# ===========================================================================
# reset_bridge
# ===========================================================================

class TestResetBridge:

    def test_reset_clears_flag(self, mock_discover):
        from src.skills import skill_bridge
        skill_bridge.ensure_initialized()
        assert skill_bridge._initialized is True
        skill_bridge.reset_bridge()
        assert skill_bridge._initialized is False


# ===========================================================================
# SkillBridge context-aware loading
# ===========================================================================

class TestSkillBridgeContextLoading:

    def test_empty_context_returns_monitoring_fallback(self, mock_discover):
        """Empty context should fallback to monitoring domain tools."""
        from src.skills.skill_bridge import SkillBridge
        bridge = SkillBridge("detect")
        tools = bridge.load_for_context({})
        assert len(tools) > 0, "Empty context should return monitoring fallback tools"
        # Verify we got monitoring-domain tools
        tool_names = [getattr(t, 'tool_name', getattr(t, '__name__', '')) for t in tools]
        monitoring_indicators = ['cw_', 'cloudwatch', 'metric', 'alarm', 'log', 'monitoring']
        has_monitoring = any(
            any(ind in name.lower() for ind in monitoring_indicators)
            for name in tool_names
        )
        assert has_monitoring, f"Fallback tools should be from monitoring domain, got: {tool_names}"

    def test_eks_context_returns_kubernetes_tools(self, mock_discover):
        """EKS pod_crash context should return kubernetes tools."""
        from src.skills.skill_bridge import SkillBridge
        bridge = SkillBridge("detect")
        tools = bridge.load_for_context({"resource_type": "eks", "alert_type": "pod_crash"})
        assert len(tools) > 0
        tool_names = [getattr(t, 'tool_name', getattr(t, '__name__', '')) for t in tools]
        k8s_indicators = ['kubectl', 'kube', 'pod', 'namespace', 'node']
        has_k8s = any(
            any(ind in name.lower() for ind in k8s_indicators)
            for name in tool_names
        )
        assert has_k8s, f"EKS context should include kubernetes tools, got: {tool_names}"

    def test_max_tools_per_invocation_enforced(self, mock_discover):
        """Tools returned should not exceed MAX_TOOLS_PER_INVOCATION."""
        from src.skills.skill_bridge import SkillBridge, MAX_TOOLS_PER_INVOCATION
        bridge = SkillBridge("sre")  # SRE has access to all tools
        tools = bridge.load_for_context({"resource_type": "eks"})
        assert len(tools) <= MAX_TOOLS_PER_INVOCATION


# ===========================================================================
# DetectAgent skills integration
# ===========================================================================

class TestDetectAgentSkills:

    @patch("src.event_correlator.get_correlator")
    @patch("src.skills.skill_bridge.get_detect_tools", return_value=[lambda: None])
    @patch("src.skills.skill_bridge.get_detect_prompt", return_value="test prompt")
    def test_init_loads_skills(self, mock_prompt, mock_tools, mock_correlator):
        from src.detect_agent import DetectAgent
        agent = DetectAgent(region="us-east-1", cache_dir="/tmp/test_detect_cache")
        assert len(agent._skill_tools) == 1
        assert agent._skill_prompt == "test prompt"

    @patch("src.event_correlator.get_correlator")
    @patch("src.skills.skill_bridge.get_detect_tools", side_effect=ImportError("no skills"))
    def test_init_graceful_failure(self, mock_tools, mock_correlator):
        from src.detect_agent import DetectAgent
        agent = DetectAgent(region="us-east-1", cache_dir="/tmp/test_detect_cache")
        assert agent._skill_tools == []
        assert agent._skill_prompt == ""

    @patch("src.event_correlator.get_correlator")
    def test_run_skills_diagnostics_no_tools(self, mock_correlator):
        from src.detect_agent import DetectAgent, DetectResult
        agent = DetectAgent(region="us-east-1", cache_dir="/tmp/test_detect_cache")
        agent._skill_tools = []
        result = DetectResult(
            detect_id="test-123",
            timestamp="2025-01-01T00:00:00+00:00",
            source="test",
            anomalies_detected=[{"type": "cpu_spike"}],
        )
        # Should return immediately without error
        agent._run_skills_diagnostics("test-123", result)
        assert "skill_diagnostics" not in (result.raw_data or {})

    @patch("src.event_correlator.get_correlator")
    @patch("src.skills.skill_bridge.execute_skill_tool")
    def test_run_skills_diagnostics_with_tools(self, mock_execute, mock_correlator):
        from src.detect_agent import DetectAgent, DetectResult

        mock_execute.return_value = json.dumps({
            "status": "success",
            "data": {"log_groups": ["app-logs"]},
        })

        agent = DetectAgent(region="us-east-1", cache_dir="/tmp/test_detect_cache")
        agent._skill_tools = [lambda: None]  # non-empty to pass guard
        result = DetectResult(
            detect_id="test-456",
            timestamp="2025-01-01T00:00:00+00:00",
            source="test",
            anomalies_detected=[{"type": "cpu_spike"}],
            raw_data={},
        )
        agent._run_skills_diagnostics("test-456", result)
        assert "skill_diagnostics" in result.raw_data
        assert len(result.raw_data["skill_diagnostics"]) == 1

    @patch("src.event_correlator.get_correlator")
    @patch("src.skills.skill_bridge.execute_skill_tool", side_effect=Exception("boom"))
    def test_run_skills_diagnostics_exception_nonfatal(self, mock_execute, mock_correlator):
        from src.detect_agent import DetectAgent, DetectResult

        agent = DetectAgent(region="us-east-1", cache_dir="/tmp/test_detect_cache")
        agent._skill_tools = [lambda: None]
        result = DetectResult(
            detect_id="test-789",
            timestamp="2025-01-01T00:00:00+00:00",
            source="test",
            anomalies_detected=[{"type": "disk_full"}],
            raw_data={},
        )
        # Should not raise
        agent._run_skills_diagnostics("test-789", result)


# ===========================================================================
# RCAInferenceEngine skills integration
# ===========================================================================

class TestRCAInferenceSkills:

    @patch("src.skills.skill_bridge.get_rca_tools", return_value=[lambda: None, lambda: None])
    @patch("src.skills.skill_bridge.get_rca_prompt", return_value="rca skills prompt")
    def test_init_loads_skills(self, mock_prompt, mock_tools):
        from src.rca_inference import RCAInferenceEngine
        engine = RCAInferenceEngine()
        assert len(engine._skill_tools) == 2
        assert engine._skill_prompt == "rca skills prompt"

    @patch("src.skills.skill_bridge.get_rca_tools", side_effect=ImportError("no skills"))
    def test_init_graceful_failure(self, mock_tools):
        from src.rca_inference import RCAInferenceEngine
        engine = RCAInferenceEngine()
        assert engine._skill_tools == []
        assert engine._skill_prompt == ""
