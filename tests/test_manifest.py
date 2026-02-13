"""
Tests for src/plugins/manifest.py — Plugin manifest system

Coverage target: 80%+ (from 0%)
"""

import os
import pytest
import yaml
import tempfile
from pathlib import Path

from src.plugins.manifest import (
    PluginManifest, ManifestLoader, create_default_manifests,
)


class TestPluginManifest:
    """Test PluginManifest dataclass."""

    def test_basic_creation(self):
        m = PluginManifest(name="Test", type="eks")
        assert m.name == "Test"
        assert m.type == "eks"
        assert m.version == "1.0.0"
        assert m.enabled is True
        assert m.icon == "🔌"

    def test_custom_fields(self):
        m = PluginManifest(
            name="Prod EKS", type="eks", version="2.0.0",
            description="Production clusters", icon="☸️",
            enabled=False, config={"regions": ["us-east-1"]},
            author="DevOps", homepage="https://example.com",
            dependencies=["base"],
        )
        assert m.version == "2.0.0"
        assert m.enabled is False
        assert m.config["regions"] == ["us-east-1"]
        assert m.author == "DevOps"

    def test_from_dict(self):
        data = {
            "name": "My Plugin",
            "type": "ec2",
            "version": "1.2.0",
            "description": "EC2 monitor",
            "enabled": True,
            "config": {"include_stopped": True},
        }
        m = PluginManifest.from_dict(data)
        assert m.name == "My Plugin"
        assert m.type == "ec2"
        assert m.version == "1.2.0"
        assert m.config["include_stopped"] is True

    def test_from_dict_defaults(self):
        m = PluginManifest.from_dict({})
        assert m.name == "Unknown"
        assert m.type == "unknown"
        assert m.version == "1.0.0"
        assert m.enabled is True

    def test_to_dict(self):
        m = PluginManifest(name="Test", type="eks", config={"x": 1})
        d = m.to_dict()
        assert d["name"] == "Test"
        assert d["type"] == "eks"
        assert d["config"] == {"x": 1}
        assert "version" in d
        assert "enabled" in d
        assert "dependencies" in d

    def test_roundtrip(self):
        original = PluginManifest(
            name="Roundtrip", type="lambda", version="3.0",
            config={"timeout": 30}, dependencies=["base", "auth"],
        )
        d = original.to_dict()
        restored = PluginManifest.from_dict(d)
        assert restored.name == original.name
        assert restored.type == original.type
        assert restored.config == original.config
        assert restored.dependencies == original.dependencies


class TestManifestLoader:
    """Test manifest file loading."""

    def test_init_default_dir(self):
        loader = ManifestLoader()
        assert loader.config_dir is not None

    def test_init_custom_dir(self):
        loader = ManifestLoader("/tmp/test-plugins")
        assert str(loader.config_dir) == "/tmp/test-plugins"

    def test_load_all_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = ManifestLoader(tmpdir)
            result = loader.load_all()
            assert result == []

    def test_load_all_nonexistent_dir(self):
        loader = ManifestLoader("/nonexistent/path")
        result = loader.load_all()
        assert result == []

    def test_load_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = Path(tmpdir) / "test.yaml"
            yaml_path.write_text(yaml.dump({
                "name": "Test Plugin",
                "type": "eks",
                "version": "1.0.0",
                "enabled": True,
            }))
            loader = ManifestLoader(tmpdir)
            m = loader.load_file(yaml_path)
            assert m.name == "Test Plugin"
            assert m.type == "eks"

    def test_load_file_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = Path(tmpdir) / "empty.yaml"
            yaml_path.write_text("")
            loader = ManifestLoader(tmpdir)
            m = loader.load_file(yaml_path)
            assert m is None

    def test_load_all_with_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for i, name in enumerate(["alpha", "beta"]):
                (Path(tmpdir) / f"{name}.yaml").write_text(yaml.dump({
                    "name": name, "type": "eks", "enabled": i == 0,
                }))
            loader = ManifestLoader(tmpdir)
            result = loader.load_all()
            assert len(result) == 2
            names = {m.name for m in result}
            assert "alpha" in names
            assert "beta" in names

    def test_load_all_skips_bad_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "good.yaml").write_text(yaml.dump({"name": "Good", "type": "eks"}))
            (Path(tmpdir) / "bad.yaml").write_text("{{invalid yaml")
            loader = ManifestLoader(tmpdir)
            result = loader.load_all()
            assert len(result) >= 1

    def test_save_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = ManifestLoader(tmpdir)
            m = PluginManifest(name="Save Test", type="ec2", config={"x": 1})
            success = loader.save_manifest(m, "save-test.yaml")
            assert success is True
            assert (Path(tmpdir) / "save-test.yaml").exists()

            # Verify content
            with open(Path(tmpdir) / "save-test.yaml") as f:
                data = yaml.safe_load(f)
            assert data["name"] == "Save Test"

    def test_save_manifest_auto_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = ManifestLoader(tmpdir)
            m = PluginManifest(name="Auto Name", type="lambda")
            success = loader.save_manifest(m)
            assert success is True

    def test_get_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.yaml").write_text(yaml.dump({"name": "Findme", "type": "eks"}))
            loader = ManifestLoader(tmpdir)
            loader.load_all()
            m = loader.get_manifest("Findme")
            assert m is not None
            assert m.name == "Findme"

    def test_get_manifest_missing(self):
        loader = ManifestLoader("/tmp")
        assert loader.get_manifest("Nope") is None

    def test_get_enabled_manifests(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "on.yaml").write_text(yaml.dump({"name": "On", "type": "eks", "enabled": True}))
            (Path(tmpdir) / "off.yaml").write_text(yaml.dump({"name": "Off", "type": "eks", "enabled": False}))
            loader = ManifestLoader(tmpdir)
            loader.load_all()
            enabled = loader.get_enabled_manifests()
            assert len(enabled) == 1
            assert enabled[0].name == "On"


class TestCreateDefaultManifests:
    """Test default manifest creation."""

    def test_creates_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifests = create_default_manifests(tmpdir)
            assert len(manifests) == 4
            names = {m.name for m in manifests}
            assert "EKS Default" in names
            assert "EC2 Monitor" in names

            # Check files were created
            yaml_files = list(Path(tmpdir).glob("*.yaml"))
            assert len(yaml_files) == 4
