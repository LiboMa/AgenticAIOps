"""Tests for src/skills/_models.py"""

import pytest
from src.skills._models import SecurityTier, ToolResult, ToolStatus, SkillManifest


class TestSecurityTier:
    def test_tier_ordering(self):
        assert SecurityTier.T0_READONLY < SecurityTier.T1_LOW_RISK
        assert SecurityTier.T1_LOW_RISK < SecurityTier.T2_HIGH_RISK
        assert SecurityTier.T2_HIGH_RISK < SecurityTier.T3_DESTRUCTIVE

    def test_tier_values(self):
        assert SecurityTier.T0_READONLY == 0
        assert SecurityTier.T3_DESTRUCTIVE == 3


class TestToolResult:
    def test_success(self):
        r = ToolResult.success({"key": "val"}, foo="bar")
        assert r.status == ToolStatus.SUCCESS
        assert r.data == {"key": "val"}
        assert r.metadata["foo"] == "bar"

    def test_blocked(self):
        r = ToolResult.blocked("not allowed", "GLOBAL_BLACKLIST")
        assert r.status == ToolStatus.BLOCKED
        assert "not allowed" in r.error
        assert r.metadata["layer"] == "GLOBAL_BLACKLIST"

    def test_fail(self):
        r = ToolResult.fail("boom")
        assert r.status == ToolStatus.ERROR
        assert r.error == "boom"

    def test_to_json(self):
        import json
        r = ToolResult.success("hello")
        parsed = json.loads(r.to_json())
        assert parsed["status"] == "success"
        assert parsed["data"] == "hello"


class TestSkillManifest:
    def test_valid_manifest(self):
        m = SkillManifest(name="test", description="A test skill")
        assert m.name == "test"

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="name"):
            SkillManifest(name="", description="test")

    def test_empty_description_raises(self):
        with pytest.raises(ValueError, match="description"):
            SkillManifest(name="test", description="")

    def test_confidence_boost_clamped(self):
        m = SkillManifest(name="test", description="test", confidence_boost=5.0)
        assert m.confidence_boost == 1.0

    def test_confidence_boost_negative_clamped(self):
        m = SkillManifest(name="test", description="test", confidence_boost=-1.0)
        assert m.confidence_boost == 0.0
