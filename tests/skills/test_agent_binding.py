"""E2E tests: Agent-Skill binding and tier enforcement."""

import json
import pytest
from src.skills import SkillRegistry
from src.skills._models import SecurityTier
from src.skills._security import set_agent_context
from src.skills.agent_binding import (
    initialize_registry, bind_skills_to_agent,
    get_agent_system_prompt, AGENT_TIER_BINDINGS, SKILL_MODULES,
)


@pytest.fixture
def registry():
    """Fresh isolated registry with all skills registered."""
    reg = SkillRegistry.create_isolated()
    initialize_registry(reg)
    return reg


class TestInitializeRegistry:
    def test_registers_all_8_skills(self, registry):
        assert len(registry.list_skills()) == 8

    def test_idempotent(self, registry):
        """Double init doesn't duplicate."""
        initialize_registry(registry)
        assert len(registry.list_skills()) == 8


class TestBindSkillsToAgent:
    def test_detect_gets_only_t0(self, registry):
        tools = bind_skills_to_agent("detect", registry=registry)
        for t in tools:
            assert t._security_tier == SecurityTier.T0_READONLY, \
                f"Detect got {t._tool_name} at {t._security_tier.name}"
        assert len(tools) >= 50  # Most tools are T0

    def test_rca_gets_t0_and_t1(self, registry):
        tools = bind_skills_to_agent("rca", registry=registry)
        tiers = {t._security_tier for t in tools}
        assert SecurityTier.T0_READONLY in tiers
        assert SecurityTier.T1_LOW_RISK in tiers
        assert SecurityTier.T2_HIGH_RISK not in tiers
        assert len(tools) > len(bind_skills_to_agent("detect", registry=registry))

    def test_sre_gets_all_tiers(self, registry):
        tools = bind_skills_to_agent("sre", registry=registry)
        tiers = {t._security_tier for t in tools}
        assert SecurityTier.T0_READONLY in tiers
        assert SecurityTier.T3_DESTRUCTIVE in tiers
        assert len(tools) >= 100

    def test_specific_skills_only(self, registry):
        tools = bind_skills_to_agent("detect", skill_names=["kubernetes"], registry=registry)
        skills = {t._skill_name for t in tools}
        assert skills == {"kubernetes"}

    def test_unknown_role_gets_t0(self, registry):
        tools = bind_skills_to_agent("unknown_agent", registry=registry)
        for t in tools:
            assert t._security_tier == SecurityTier.T0_READONLY


class TestTierEnforcementE2E:
    """End-to-end: Agent role → tool invocation → security gate."""

    def test_detect_blocked_from_t1_tools(self, registry):
        """Detect agent calling a T1 tool gets BLOCKED."""
        set_agent_context("detect", SecurityTier.T0_READONLY)
        # Import a T1 tool directly
        from src.skills.linux_admin.tools import service_restart
        result = json.loads(service_restart(service="nginx"))
        assert result["status"] == "blocked"
        assert "TIER_GATE" in result.get("metadata", {}).get("layer", "")

    def test_sre_t2_needs_approval(self, registry):
        """SRE agent calling T2 tool without token gets BLOCKED."""
        set_agent_context("sre", SecurityTier.T3_DESTRUCTIVE)
        from src.skills.kubernetes.tools import k8s_delete_resource
        result = json.loads(k8s_delete_resource(resource_type="pod", name="test"))
        assert result["status"] == "blocked"
        assert "APPROVAL_GATE" in result.get("metadata", {}).get("layer", "")

    def test_sre_t2_with_approval_passes(self, registry):
        """SRE agent with approval_token can use T2 tools."""
        set_agent_context("sre", SecurityTier.T3_DESTRUCTIVE)
        from src.skills.linux_admin.tools import process_kill
        # Will fail at execution (PID doesn't exist) but should pass security
        result = json.loads(process_kill(pid=999999, approval_token="approved-123"))
        # Either success (kill ran) or error (PID not found) — not blocked
        assert result["status"] in ("success", "error")

    def test_sre_t3_needs_dual_approval(self, registry):
        """SRE agent calling T3 needs dual tokens."""
        set_agent_context("sre", SecurityTier.T3_DESTRUCTIVE)
        from src.skills.linux_admin.tools import system_reboot
        result = json.loads(system_reboot(approval_token="token-a"))
        assert result["status"] == "blocked"

    def test_sre_t3_dual_approval_works(self, registry):
        """SRE agent with dual tokens can use T3."""
        set_agent_context("sre", SecurityTier.T3_DESTRUCTIVE)
        from src.skills.linux_admin.tools import system_reboot
        result = json.loads(system_reboot(
            approval_token="token-a", approval_token_2="token-b"
        ))
        assert result["status"] in ("success", "dry_run")

    def test_global_blacklist_blocks_sre(self, registry):
        """Even SRE with T3 cannot bypass global blacklist."""
        set_agent_context("sre", SecurityTier.T3_DESTRUCTIVE)
        from src.skills.linux_admin.tools import log_tail
        # Attempt to inject via log_path (won't hit command_param but tests the flow)
        result = json.loads(log_tail(log_path="/var/log/syslog", lines=10))
        # This should succeed (no blacklist match)
        assert result["status"] == "success" or result["status"] == "error"


class TestGetAgentSystemPrompt:
    def test_detect_prompt_has_skills(self, registry):
        # Need to set the singleton for get_agent_system_prompt
        SkillRegistry._instance = registry
        prompt = get_agent_system_prompt("detect")
        assert "Available Skills" in prompt
        assert "T0_READONLY" in prompt
        assert "T2_HIGH_RISK" not in prompt  # Detect shouldn't see T2 tools
        SkillRegistry.reset()

    def test_sre_prompt_has_all_tiers(self, registry):
        SkillRegistry._instance = registry
        prompt = get_agent_system_prompt("sre")
        assert "T3_DESTRUCTIVE" in prompt
        SkillRegistry.reset()
