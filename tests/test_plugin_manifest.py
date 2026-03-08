"""Tests for plugins/manifest — PluginManifest, ManifestLoader, create_default_manifests."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.plugins.manifest import (
    PluginManifest,
    ManifestLoader,
    create_default_manifests,
)


class TestPluginManifest:

    def test_creation_defaults(self):
        m = PluginManifest(name="Test", type="test")
        assert m.version == "1.0.0"
        assert m.enabled is True
        assert m.icon == "🔌"

    def test_from_dict(self):
        data = {
            "name": "EKS Prod",
            "type": "eks",
            "version": "2.0.0",
            "description": "Production EKS",
            "enabled": False,
            "config": {"regions": ["us-east-1"]},
        }
        m = PluginManifest.from_dict(data)
        assert m.name == "EKS Prod"
        assert m.type == "eks"
        assert m.version == "2.0.0"
        assert m.enabled is False
        assert m.config["regions"] == ["us-east-1"]

    def test_from_dict_minimal(self):
        m = PluginManifest.from_dict({})
        assert m.name == "Unknown"
        assert m.type == "unknown"

    def test_to_dict(self):
        m = PluginManifest(name="Test", type="test", description="Desc")
        d = m.to_dict()
        assert d["name"] == "Test"
        assert d["type"] == "test"
        assert d["description"] == "Desc"
        assert "config" in d
        assert "dependencies" in d

    def test_roundtrip(self):
        original = PluginManifest(
            name="RT", type="eks", version="1.2.3",
            config={"key": "val"}, dependencies=["dep1"],
        )
        restored = PluginManifest.from_dict(original.to_dict())
        assert restored.name == original.name
        assert restored.config == original.config
        assert restored.dependencies == original.dependencies


class TestManifestLoader:

    def test_load_all_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            loader = ManifestLoader(config_dir=d)
            result = loader.load_all()
            assert result == []

    def test_load_all_nonexistent_dir(self):
        loader = ManifestLoader(config_dir="/nonexistent/path")
        result = loader.load_all()
        assert result == []

    def test_load_and_save(self):
        with tempfile.TemporaryDirectory() as d:
            loader = ManifestLoader(config_dir=d)
            manifest = PluginManifest(
                name="TestPlugin", type="test",
                description="Test plugin",
                config={"key": "value"},
            )
            ok = loader.save_manifest(manifest, "test-plugin.yaml")
            assert ok is True
            assert (Path(d) / "test-plugin.yaml").exists()

            # Reload
            loaded = loader.load_all()
            assert len(loaded) == 1
            assert loaded[0].name == "TestPlugin"

    def test_save_auto_filename(self):
        with tempfile.TemporaryDirectory() as d:
            loader = ManifestLoader(config_dir=d)
            manifest = PluginManifest(name="My Plugin", type="eks")
            ok = loader.save_manifest(manifest)
            assert ok is True
            assert (Path(d) / "eks-my-plugin.yaml").exists()

    def test_load_file_empty_yaml(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "empty.yaml"
            f.write_text("")
            loader = ManifestLoader(config_dir=d)
            result = loader.load_file(f)
            assert result is None

    def test_get_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            loader = ManifestLoader(config_dir=d)
            manifest = PluginManifest(name="TestPlugin", type="test")
            loader.save_manifest(manifest, "test.yaml")
            loader.load_all()

            assert loader.get_manifest("TestPlugin") is not None
            assert loader.get_manifest("Nonexistent") is None

    def test_get_enabled_manifests(self):
        with tempfile.TemporaryDirectory() as d:
            loader = ManifestLoader(config_dir=d)
            loader.save_manifest(PluginManifest(name="A", type="a", enabled=True), "a.yaml")
            loader.save_manifest(PluginManifest(name="B", type="b", enabled=False), "b.yaml")
            loader.load_all()

            enabled = loader.get_enabled_manifests()
            names = [m.name for m in enabled]
            assert "A" in names
            assert "B" not in names

    def test_load_invalid_yaml(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "bad.yaml"
            f.write_text("{{{{invalid yaml")
            loader = ManifestLoader(config_dir=d)
            result = loader.load_all()
            assert result == []


class TestCreateDefaults:

    def test_create_default_manifests(self):
        with tempfile.TemporaryDirectory() as d:
            manifests = create_default_manifests(config_dir=d)
            assert len(manifests) == 4
            yaml_files = list(Path(d).glob("*.yaml"))
            assert len(yaml_files) == 4
