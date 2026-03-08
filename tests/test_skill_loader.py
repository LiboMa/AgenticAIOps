"""Tests for SkillLoader — discover, load, safety, tools."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from src.aci.skills.loader import SkillLoader, _is_strands_tool
from src.aci.skills.models import SafetyConfig, SafetyTier, SkillDefinition, SkillSummary


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    """Create a minimal skills directory with two test skills."""
    # Skill 1: linux-admin (full structure)
    linux = tmp_path / "linux-admin"
    linux.mkdir()

    (linux / "SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: linux-admin
        description: >
          Diagnose and resolve Linux system issues including process
          management, disk usage, memory pressure, and log analysis.
        license: Apache-2.0
        metadata:
          author: agenticaiops
          version: "1.0"
        allowed-tools: Bash(ssh:*) Bash(shell:*)
        ---

        # Linux Admin Skill

        You are an expert Linux system administrator.

        ## Rules
        - Read before write
        - Least privilege
    """))

    # safety/
    safety = linux / "safety"
    safety.mkdir()
    (safety / "safety_tier.yaml").write_text(yaml.dump({
        "tier": "guarded",
        "requires_approval": ["reboot", "shutdown"],
        "deny_by_default": False,
    }))
    (safety / "blast_radius.yaml").write_text(yaml.dump({
        "scope": "single-host",
        "high_impact": {"reboot": "Full host restart"},
    }))

    # references/
    refs = linux / "references"
    refs.mkdir()
    (refs / "TROUBLESHOOT.md").write_text("# Troubleshooting Guide\n\nStep 1...")
    (refs / "DANGEROUS_OPS.md").write_text("# Dangerous Operations\n\n- rm -rf /")

    # scripts/ (no real @tool — tested separately)
    scripts = linux / "scripts"
    scripts.mkdir()
    (scripts / "diagnose.py").write_text(textwrap.dedent("""\
        def dummy_diagnose():
            return "ok"
    """))

    # Skill 2: monitoring (minimal)
    mon = tmp_path / "monitoring"
    mon.mkdir()
    (mon / "SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: monitoring
        description: Monitor CloudWatch, Datadog, Grafana, and Prometheus.
        ---

        # Monitoring Skill

        Check metrics and alerts.
    """))

    # Non-skill directory (no SKILL.md)
    (tmp_path / "not-a-skill").mkdir()
    (tmp_path / "not-a-skill" / "README.md").write_text("Not a skill")

    return tmp_path


@pytest.fixture
def loader(skills_dir: Path) -> SkillLoader:
    return SkillLoader(skills_dir)


# ── Discovery Tests ─────────────────────────────────────────────


class TestDiscover:
    def test_discover_finds_all_skills(self, loader: SkillLoader) -> None:
        summaries = loader.discover()
        names = [s.name for s in summaries]
        assert "linux-admin" in names
        assert "monitoring" in names
        assert len(summaries) == 2

    def test_discover_sorted_by_name(self, loader: SkillLoader) -> None:
        summaries = loader.discover()
        assert summaries[0].name == "linux-admin"
        assert summaries[1].name == "monitoring"

    def test_discover_skips_non_skills(self, loader: SkillLoader) -> None:
        summaries = loader.discover()
        names = [s.name for s in summaries]
        assert "not-a-skill" not in names

    def test_discover_empty_dir(self, tmp_path: Path) -> None:
        loader = SkillLoader(tmp_path / "nonexistent")
        assert loader.discover() == []

    def test_summary_has_required_fields(self, loader: SkillLoader) -> None:
        summaries = loader.discover()
        s = next(s for s in summaries if s.name == "linux-admin")
        assert s.description  # non-empty
        assert s.path.is_dir()
        assert s.license == "Apache-2.0"
        assert s.author == "agenticaiops"
        assert s.version == "1.0"

    def test_summary_allowed_tools_parsed(self, loader: SkillLoader) -> None:
        summaries = loader.discover()
        s = next(s for s in summaries if s.name == "linux-admin")
        assert s.allowed_tools == ["Bash(ssh:*)", "Bash(shell:*)"]

    def test_summary_minimal_skill(self, loader: SkillLoader) -> None:
        summaries = loader.discover()
        s = next(s for s in summaries if s.name == "monitoring")
        assert s.description == "Monitor CloudWatch, Datadog, Grafana, and Prometheus."
        assert s.allowed_tools == []  # not specified
        assert s.version == "0.1.0"  # default


# ── Load Tests ──────────────────────────────────────────────────


class TestLoad:
    def test_load_returns_definition(self, loader: SkillLoader) -> None:
        skill = loader.load("linux-admin")
        assert isinstance(skill, SkillDefinition)
        assert skill.name == "linux-admin"

    def test_load_instructions(self, loader: SkillLoader) -> None:
        skill = loader.load("linux-admin")
        assert "# Linux Admin Skill" in skill.instructions
        assert "Read before write" in skill.instructions

    def test_load_caches(self, loader: SkillLoader) -> None:
        s1 = loader.load("linux-admin")
        s2 = loader.load("linux-admin")
        assert s1 is s2

    def test_load_missing_skill(self, loader: SkillLoader) -> None:
        with pytest.raises(FileNotFoundError, match="nonexistent"):
            loader.load("nonexistent")

    def test_load_all(self, loader: SkillLoader) -> None:
        skills = loader.load_all()
        assert len(skills) == 2
        names = {s.name for s in skills}
        assert names == {"linux-admin", "monitoring"}


# ── Safety Config Tests ─────────────────────────────────────────


class TestSafety:
    def test_safety_tier_loaded(self, loader: SkillLoader) -> None:
        skill = loader.load("linux-admin")
        assert skill.safety.tier == SafetyTier.GUARDED

    def test_safety_requires_approval(self, loader: SkillLoader) -> None:
        skill = loader.load("linux-admin")
        assert "reboot" in skill.safety.requires_approval
        assert "shutdown" in skill.safety.requires_approval

    def test_safety_deny_by_default(self, loader: SkillLoader) -> None:
        skill = loader.load("linux-admin")
        assert skill.safety.deny_by_default is False

    def test_safety_blast_radius(self, loader: SkillLoader) -> None:
        skill = loader.load("linux-admin")
        assert skill.safety.blast_radius["scope"] == "single-host"

    def test_safety_defaults_when_missing(self, loader: SkillLoader) -> None:
        skill = loader.load("monitoring")
        assert skill.safety.tier == SafetyTier.READ_ONLY  # default
        assert skill.safety.deny_by_default is True  # default


# ── References Tests ────────────────────────────────────────────


class TestReferences:
    def test_list_references(self, loader: SkillLoader) -> None:
        skill = loader.load("linux-admin")
        refs = skill.list_references()
        assert "TROUBLESHOOT.md" in refs
        assert "DANGEROUS_OPS.md" in refs

    def test_get_reference(self, loader: SkillLoader) -> None:
        skill = loader.load("linux-admin")
        content = skill.get_reference("TROUBLESHOOT.md")
        assert content is not None
        assert "Troubleshooting Guide" in content

    def test_get_reference_missing(self, loader: SkillLoader) -> None:
        skill = loader.load("linux-admin")
        assert skill.get_reference("NONEXISTENT.md") is None

    def test_no_references_dir(self, loader: SkillLoader) -> None:
        skill = loader.load("monitoring")
        assert skill.list_references() == []


# ── Tools Discovery Tests ───────────────────────────────────────


class TestToolDiscovery:
    def test_is_strands_tool_positive(self) -> None:
        def fake_tool():
            pass
        fake_tool.tool_name = "test"
        assert _is_strands_tool(fake_tool) is True

    def test_is_strands_tool_negative(self) -> None:
        def plain_func():
            pass
        assert _is_strands_tool(plain_func) is False

    def test_is_strands_tool_handler(self) -> None:
        def handler_tool():
            pass
        handler_tool.tool_handler = True
        assert _is_strands_tool(handler_tool) is True

    def test_scripts_without_tools(self, loader: SkillLoader) -> None:
        skill = loader.load("linux-admin")
        # dummy_diagnose has no @tool decorator
        assert len(skill.get_tools()) == 0


# ── Model Validation Tests ──────────────────────────────────────


class TestModels:
    def test_summary_requires_name(self) -> None:
        with pytest.raises(ValueError, match="name is required"):
            SkillSummary(name="", description="test", path=Path("/tmp"))

    def test_summary_requires_description(self) -> None:
        with pytest.raises(ValueError, match="description is required"):
            SkillSummary(name="test", description="", path=Path("/tmp"))

    def test_summary_description_max_length(self) -> None:
        with pytest.raises(ValueError, match="exceeds 1024"):
            SkillSummary(name="test", description="x" * 1025, path=Path("/tmp"))

    def test_safety_tier_enum(self) -> None:
        assert SafetyTier.READ_ONLY.value == "read-only"
        assert SafetyTier.GUARDED.value == "guarded"
        assert SafetyTier.DESTRUCTIVE.value == "destructive"

    def test_get_agent_tools_dedup(self) -> None:
        """get_agent_tools deduplicates by function name."""
        def tool_a():
            pass
        tool_a.tool_name = "tool_a"

        s1 = SkillDefinition(
            summary=SkillSummary(name="s1", description="test", path=Path("/tmp")),
            instructions="",
            _tools=[tool_a],
        )
        s2 = SkillDefinition(
            summary=SkillSummary(name="s2", description="test2", path=Path("/tmp")),
            instructions="",
            _tools=[tool_a],  # same function
        )
        tools = SkillLoader.get_agent_tools(s1, s2)
        assert len(tools) == 1


# ── Frontmatter Edge Cases ──────────────────────────────────────


class TestFrontmatterEdgeCases:
    def test_no_frontmatter(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "bare"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Just markdown\n\nNo frontmatter here.")
        loader = SkillLoader(tmp_path)
        # discover should fail gracefully (no frontmatter = ValueError)
        summaries = loader.discover()
        assert len(summaries) == 0  # skipped

    def test_empty_frontmatter(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "empty-fm"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\n---\n# Empty")
        loader = SkillLoader(tmp_path)
        # Should skip — name defaults to dir name but description is empty
        summaries = loader.discover()
        assert len(summaries) == 0  # empty description = ValueError

    def test_name_defaults_to_dirname(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\ndescription: A skill without explicit name\n---\n# Content"
        )
        loader = SkillLoader(tmp_path)
        summaries = loader.discover()
        assert len(summaries) == 1
        assert summaries[0].name == "my-skill"  # falls back to dir name
