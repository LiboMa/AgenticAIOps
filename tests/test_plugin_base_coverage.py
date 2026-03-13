"""
Tests for src/plugins/base.py — target 76% → 100% coverage.
Covers: PluginConfig.to_dict, ClusterConfig.to_dict, PluginBase.enable/disable/get_info,
PluginRegistry singleton, register_plugin_class, get_available_plugins, create_plugin,
get_plugin, get_all_plugins, get_enabled_plugins, remove_plugin, cluster management,
get_all_tools, get_status, load_from_manifests, save_to_manifest.
"""

import pytest
from unittest.mock import patch, MagicMock
from typing import Dict, List, Any, Callable

from src.plugins.base import (
    PluginBase,
    PluginConfig,
    PluginStatus,
    PluginRegistry,
    ClusterConfig,
)


# ── Concrete plugin for testing ──────────────────────────────────────

class _DummyPlugin(PluginBase):
    PLUGIN_TYPE = "dummy"
    PLUGIN_NAME = "Dummy"
    PLUGIN_DESCRIPTION = "A dummy plugin"
    PLUGIN_ICON = "🧪"

    def __init__(self, config, *, init_ok=True):
        super().__init__(config)
        self._init_ok = init_ok

    def initialize(self) -> bool:
        return self._init_ok

    def health_check(self) -> Dict[str, Any]:
        return {"ok": True}

    def get_tools(self) -> List[Callable]:
        return [lambda: "tool1"]

    def get_resources(self) -> List[Dict[str, Any]]:
        return [{"id": "r1"}]

    def get_status_summary(self) -> Dict[str, Any]:
        return {"status": "ok"}


class _FailPlugin(_DummyPlugin):
    """Plugin whose initialize() raises."""
    PLUGIN_TYPE = "fail"
    PLUGIN_NAME = "Fail"

    def initialize(self) -> bool:
        raise RuntimeError("init boom")


@pytest.fixture(autouse=True)
def _reset_registry():
    """Save and restore the singleton state around each test."""
    saved = (
        dict(PluginRegistry._plugin_classes),
        dict(PluginRegistry._plugins),
        dict(PluginRegistry._clusters),
        PluginRegistry._active_cluster,
    )
    PluginRegistry._plugin_classes = {}
    PluginRegistry._plugins = {}
    PluginRegistry._clusters = {}
    PluginRegistry._active_cluster = None
    yield
    PluginRegistry._plugin_classes = saved[0]
    PluginRegistry._plugins = saved[1]
    PluginRegistry._clusters = saved[2]
    PluginRegistry._active_cluster = saved[3]


def _cfg(pid="p1", ptype="dummy", name="d1", enabled=True, config=None):
    return PluginConfig(
        plugin_id=pid,
        plugin_type=ptype,
        name=name,
        enabled=enabled,
        config=config or {},
    )


# ── PluginConfig ─────────────────────────────────────────────────────

class TestPluginConfig:
    def test_to_dict(self):
        c = _cfg(config={"k": "v"})
        d = c.to_dict()
        assert d["plugin_id"] == "p1"
        assert d["config"] == {"k": "v"}


# ── ClusterConfig ────────────────────────────────────────────────────

class TestClusterConfig:
    def test_to_dict(self):
        cc = ClusterConfig(cluster_id="c1", name="Cluster", region="us-east-1",
                           plugin_type="eks", config={"a": 1})
        d = cc.to_dict()
        assert d["cluster_id"] == "c1"
        assert d["region"] == "us-east-1"
        assert d["config"] == {"a": 1}


# ── PluginBase ───────────────────────────────────────────────────────

class TestPluginBase:
    def test_enable_success(self):
        p = _DummyPlugin(_cfg())
        assert p.enable() is True
        assert p.status == PluginStatus.ENABLED

    def test_enable_init_returns_false(self):
        p = _DummyPlugin(_cfg(), init_ok=False)
        assert p.enable() is False
        assert p.status != PluginStatus.ENABLED

    def test_enable_init_raises(self):
        p = _FailPlugin(_cfg(ptype="fail"))
        assert p.enable() is False
        assert p.status == PluginStatus.ERROR

    def test_disable(self):
        p = _DummyPlugin(_cfg())
        p.enable()
        assert p.disable() is True
        assert p.status == PluginStatus.DISABLED

    def test_get_info(self):
        p = _DummyPlugin(_cfg())
        p.enable()
        info = p.get_info()
        assert info["plugin_type"] == "dummy"
        assert info["status"] == "enabled"
        assert info["tools_count"] == 1
        assert info["icon"] == "🧪"


# ── PluginRegistry ───────────────────────────────────────────────────

class TestPluginRegistry:
    def test_singleton(self):
        a = PluginRegistry()
        b = PluginRegistry()
        assert a is b

    def test_register_and_get_available(self):
        PluginRegistry.register_plugin_class(_DummyPlugin)
        avail = PluginRegistry.get_available_plugins()
        assert len(avail) == 1
        assert avail[0]["type"] == "dummy"
        assert avail[0]["name"] == "Dummy"

    def test_create_plugin_enables_when_enabled(self):
        PluginRegistry.register_plugin_class(_DummyPlugin)
        p = PluginRegistry.create_plugin(_cfg())
        assert p is not None
        assert p.status == PluginStatus.ENABLED

    def test_create_plugin_disabled(self):
        PluginRegistry.register_plugin_class(_DummyPlugin)
        p = PluginRegistry.create_plugin(_cfg(enabled=False))
        assert p is not None
        assert p.status == PluginStatus.DISABLED

    def test_create_plugin_unknown_type(self):
        assert PluginRegistry.create_plugin(_cfg(ptype="nope")) is None

    def test_get_plugin(self):
        PluginRegistry.register_plugin_class(_DummyPlugin)
        PluginRegistry.create_plugin(_cfg())
        assert PluginRegistry.get_plugin("p1") is not None
        assert PluginRegistry.get_plugin("nope") is None

    def test_get_all_plugins(self):
        PluginRegistry.register_plugin_class(_DummyPlugin)
        PluginRegistry.create_plugin(_cfg(pid="a"))
        PluginRegistry.create_plugin(_cfg(pid="b"))
        assert len(PluginRegistry.get_all_plugins()) == 2

    def test_get_enabled_plugins(self):
        PluginRegistry.register_plugin_class(_DummyPlugin)
        PluginRegistry.create_plugin(_cfg(pid="a"))
        PluginRegistry.create_plugin(_cfg(pid="b", enabled=False))
        enabled = PluginRegistry.get_enabled_plugins()
        assert len(enabled) == 1

    def test_remove_plugin(self):
        PluginRegistry.register_plugin_class(_DummyPlugin)
        PluginRegistry.create_plugin(_cfg())
        assert PluginRegistry.remove_plugin("p1") is True
        assert PluginRegistry.get_plugin("p1") is None

    def test_remove_plugin_not_found(self):
        assert PluginRegistry.remove_plugin("nope") is False

    # ── Cluster management ───────────────────────────────────────────

    def test_add_get_cluster(self):
        cc = ClusterConfig("c1", "Cls", "us-east-1", "eks")
        PluginRegistry.add_cluster(cc)
        assert PluginRegistry.get_cluster("c1") is cc
        assert PluginRegistry.get_cluster("nope") is None

    def test_get_all_clusters(self):
        PluginRegistry.add_cluster(ClusterConfig("c1", "A", "r1", "eks"))
        PluginRegistry.add_cluster(ClusterConfig("c2", "B", "r2", "hpc"))
        assert len(PluginRegistry.get_all_clusters()) == 2

    def test_get_clusters_by_type(self):
        PluginRegistry.add_cluster(ClusterConfig("c1", "A", "r1", "eks"))
        PluginRegistry.add_cluster(ClusterConfig("c2", "B", "r2", "hpc"))
        assert len(PluginRegistry.get_clusters_by_type("eks")) == 1

    def test_set_active_cluster(self):
        PluginRegistry.add_cluster(ClusterConfig("c1", "A", "r1", "eks"))
        assert PluginRegistry.set_active_cluster("c1") is True
        assert PluginRegistry.get_active_cluster().cluster_id == "c1"

    def test_set_active_cluster_not_found(self):
        assert PluginRegistry.set_active_cluster("nope") is False

    def test_get_active_cluster_none(self):
        assert PluginRegistry.get_active_cluster() is None

    # ── get_all_tools / get_status ───────────────────────────────────

    def test_get_all_tools(self):
        PluginRegistry.register_plugin_class(_DummyPlugin)
        PluginRegistry.create_plugin(_cfg())
        tools = PluginRegistry.get_all_tools()
        assert len(tools) == 1

    def test_get_status(self):
        PluginRegistry.register_plugin_class(_DummyPlugin)
        PluginRegistry.create_plugin(_cfg())
        PluginRegistry.add_cluster(ClusterConfig("c1", "A", "r1", "eks"))
        st = PluginRegistry.get_status()
        assert st["available_plugin_types"] == 1
        assert st["registered_plugins"] == 1
        assert st["enabled_plugins"] == 1
        assert st["clusters"] == 1
        assert len(st["plugins"]) == 1
        assert len(st["cluster_list"]) == 1

    # ── load_from_manifests / save_to_manifest ───────────────────────

    def test_load_from_manifests(self):
        PluginRegistry.register_plugin_class(_DummyPlugin)

        mock_manifest = MagicMock()
        mock_manifest.enabled = True
        mock_manifest.type = "dummy"
        mock_manifest.name = "M1"
        mock_manifest.config = {}

        from src.plugins import manifest as mmod
        loader_inst = MagicMock()
        loader_inst.load_all.return_value = [mock_manifest]
        with patch.object(mmod, "ManifestLoader", return_value=loader_inst):
            loaded = PluginRegistry.load_from_manifests("/tmp/fake")
            assert loaded == 1

    def test_load_from_manifests_disabled_skipped(self):
        mock_manifest = MagicMock()
        mock_manifest.enabled = False
        mock_manifest.type = "dummy"
        mock_manifest.name = "Dis"

        from src.plugins import manifest as mmod
        loader_inst = MagicMock()
        loader_inst.load_all.return_value = [mock_manifest]
        with patch.object(mmod, "ManifestLoader", return_value=loader_inst):
            loaded = PluginRegistry.load_from_manifests("/tmp")
            assert loaded == 0

    def test_save_to_manifest_success(self):
        PluginRegistry.register_plugin_class(_DummyPlugin)
        PluginRegistry.create_plugin(_cfg())

        from src.plugins import manifest as mmod
        loader_inst = MagicMock()
        loader_inst.save_manifest.return_value = True
        with patch.object(mmod, "ManifestLoader", return_value=loader_inst):
            assert PluginRegistry.save_to_manifest("p1", "/tmp") is True

    def test_save_to_manifest_not_found(self):
        assert PluginRegistry.save_to_manifest("nope") is False
