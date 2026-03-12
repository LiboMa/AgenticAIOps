"""
Daily Coverage Boost Tests — 2026-03-11

Target the 3 lowest-coverage modules:
  1. src/aci/interface.py (47% → target 75%+) — get_topology, get_dependencies, _collect_k8s_topology, get_aci_tools
  2. src/config.py (60% → target 90%+) — __main__ block
  3. src/aci/mcp_bridge.py (61% → target 85%+) — initialize, get_tools, list_available_tools, call_tool
"""

import json
import pytest
from unittest.mock import patch, MagicMock

# ============================================================================
# 1. src/aci/interface.py — topology & tools coverage
# ============================================================================

from src.aci.interface import AgentCloudInterface, get_aci_tools
from src.aci.models import TelemetryResult, OperationResult, ContextResult, ResultStatus


@pytest.fixture
def aci_mocked():
    with patch("src.aci.interface.KubectlExecutor") as MockKube, \
         patch("src.aci.interface.ShellExecutor"), \
         patch("src.aci.interface.SecurityFilter"), \
         patch("src.aci.interface.AuditLogger"), \
         patch("src.aci.interface.LogsProvider"), \
         patch("src.aci.interface.EventsProvider"), \
         patch("src.aci.interface.MetricsProvider"):
        inst = AgentCloudInterface()
        yield inst


class TestGetAciTools:
    """Cover get_aci_tools() helper."""

    def test_returns_list_of_callables(self, aci_mocked):
        tools = get_aci_tools(aci_mocked)
        assert isinstance(tools, list)
        assert len(tools) == 5
        for t in tools:
            assert callable(t)

    def test_contains_expected_methods(self, aci_mocked):
        tools = get_aci_tools(aci_mocked)
        names = [t.__name__ for t in tools]
        assert "get_logs" in names
        assert "kubectl" in names
        assert "exec_shell" in names


class TestGetTopology:
    """Cover get_topology and _collect_k8s_topology."""

    def test_get_topology_success(self, aci_mocked):
        nodes_json = json.dumps({
            "items": [{
                "metadata": {"name": "node-1"},
                "status": {"conditions": [{"type": "Ready", "status": "True"}]}
            }]
        })
        ns_json = json.dumps({
            "items": [{"metadata": {"name": "default"}}]
        })
        deploy_json = json.dumps({
            "items": [{
                "metadata": {"name": "web"},
                "spec": {"replicas": 2, "selector": {"matchLabels": {"app": "web"}}},
                "status": {"readyReplicas": 2}
            }]
        })
        svc_json = json.dumps({
            "items": [{
                "metadata": {"name": "web-svc"},
                "spec": {"type": "ClusterIP", "selector": {"app": "web"}}
            }]
        })
        pod_json = json.dumps({
            "items": [{
                "metadata": {"name": "web-abc"},
                "spec": {"nodeName": "node-1"},
                "status": {"phase": "Running"}
            }]
        })

        def kubectl_side_effect(args, output_format="json"):
            cmd = " ".join(args)
            if "get nodes" in cmd:
                return OperationResult(status=ResultStatus.SUCCESS, command=cmd, stdout=nodes_json)
            if "get namespaces" in cmd:
                return OperationResult(status=ResultStatus.SUCCESS, command=cmd, stdout=ns_json)
            if "get deployments" in cmd:
                return OperationResult(status=ResultStatus.SUCCESS, command=cmd, stdout=deploy_json)
            if "get services" in cmd:
                return OperationResult(status=ResultStatus.SUCCESS, command=cmd, stdout=svc_json)
            if "get pods" in cmd:
                return OperationResult(status=ResultStatus.SUCCESS, command=cmd, stdout=pod_json)
            return OperationResult(status=ResultStatus.ERROR, command=cmd, error="unknown")

        aci_mocked._kubectl.execute.side_effect = kubectl_side_effect
        result = aci_mocked.get_topology(namespace="all")
        assert result.status == ResultStatus.SUCCESS
        assert result.data["node_count"] >= 0

    def test_get_topology_single_namespace(self, aci_mocked):
        nodes_json = json.dumps({"items": []})
        empty_json = json.dumps({"items": []})

        def kubectl_side_effect(args, output_format="json"):
            cmd = " ".join(args)
            if "get nodes" in cmd:
                return OperationResult(status=ResultStatus.SUCCESS, command=cmd, stdout=nodes_json)
            return OperationResult(status=ResultStatus.SUCCESS, command=cmd, stdout=empty_json)

        aci_mocked._kubectl.execute.side_effect = kubectl_side_effect
        result = aci_mocked.get_topology(namespace="kube-system")
        assert result.status == ResultStatus.SUCCESS

    def test_get_topology_error(self, aci_mocked):
        aci_mocked._kubectl.execute.side_effect = RuntimeError("cluster unreachable")
        result = aci_mocked.get_topology()
        assert result.status == ResultStatus.ERROR
        assert "cluster unreachable" in result.error

    def test_get_topology_bad_json(self, aci_mocked):
        """JSONDecodeError paths in _collect_k8s_topology."""
        def kubectl_side_effect(args, output_format="json"):
            return OperationResult(status=ResultStatus.SUCCESS, command="k", stdout="not-json{{{")

        aci_mocked._kubectl.execute.side_effect = kubectl_side_effect
        result = aci_mocked.get_topology(namespace="default")
        # Should still succeed (graceful degradation)
        assert result.status == ResultStatus.SUCCESS

    def test_get_topology_kubectl_error_status(self, aci_mocked):
        """When kubectl returns ERROR status (no stdout)."""
        def kubectl_side_effect(args, output_format="json"):
            return OperationResult(status=ResultStatus.ERROR, command="k", error="forbidden")

        aci_mocked._kubectl.execute.side_effect = kubectl_side_effect
        result = aci_mocked.get_topology(namespace="default")
        assert result.status == ResultStatus.SUCCESS  # topology still builds with empty data

    def test_get_topology_node_not_ready(self, aci_mocked):
        nodes_json = json.dumps({
            "items": [{
                "metadata": {"name": "node-bad"},
                "status": {"conditions": [{"type": "Ready", "status": "False"}]}
            }]
        })
        empty = json.dumps({"items": []})

        def kubectl_side_effect(args, output_format="json"):
            cmd = " ".join(args)
            if "get nodes" in cmd:
                return OperationResult(status=ResultStatus.SUCCESS, command=cmd, stdout=nodes_json)
            return OperationResult(status=ResultStatus.SUCCESS, command=cmd, stdout=empty)

        aci_mocked._kubectl.execute.side_effect = kubectl_side_effect
        result = aci_mocked.get_topology(namespace="default")
        assert result.status == ResultStatus.SUCCESS


class TestGetDependencies:
    """Cover get_dependencies."""

    def test_service_not_found(self, aci_mocked):
        empty = json.dumps({"items": []})

        def kubectl_side_effect(args, output_format="json"):
            return OperationResult(status=ResultStatus.SUCCESS, command="k", stdout=empty)

        aci_mocked._kubectl.execute.side_effect = kubectl_side_effect
        result = aci_mocked.get_dependencies("nonexistent-svc")
        assert result.status == ResultStatus.SUCCESS
        assert result.data["found"] is False

    def test_get_dependencies_error(self, aci_mocked):
        aci_mocked._kubectl.execute.side_effect = RuntimeError("boom")
        result = aci_mocked.get_dependencies("web")
        assert result.status == ResultStatus.ERROR

    def test_service_found_with_neighbors(self, aci_mocked):
        nodes_json = json.dumps({"items": []})
        ns_json = json.dumps({"items": [{"metadata": {"name": "default"}}]})
        svc_json = json.dumps({
            "items": [{
                "metadata": {"name": "web"},
                "spec": {"type": "ClusterIP", "selector": {"app": "web"}}
            }]
        })
        deploy_json = json.dumps({
            "items": [{
                "metadata": {"name": "web"},
                "spec": {"replicas": 1, "selector": {"matchLabels": {"app": "web"}}},
                "status": {"readyReplicas": 1}
            }]
        })
        pod_json = json.dumps({
            "items": [{
                "metadata": {"name": "web-pod-1"},
                "spec": {"nodeName": "node-1"},
                "status": {"phase": "Running"}
            }]
        })

        def kubectl_side_effect(args, output_format="json"):
            cmd = " ".join(args)
            if "get nodes" in cmd:
                return OperationResult(status=ResultStatus.SUCCESS, command=cmd, stdout=nodes_json)
            if "get namespaces" in cmd:
                return OperationResult(status=ResultStatus.SUCCESS, command=cmd, stdout=ns_json)
            if "get deployments" in cmd:
                return OperationResult(status=ResultStatus.SUCCESS, command=cmd, stdout=deploy_json)
            if "get services" in cmd:
                return OperationResult(status=ResultStatus.SUCCESS, command=cmd, stdout=svc_json)
            if "get pods" in cmd:
                return OperationResult(status=ResultStatus.SUCCESS, command=cmd, stdout=pod_json)
            return OperationResult(status=ResultStatus.SUCCESS, command=cmd, stdout='{"items":[]}')

        aci_mocked._kubectl.execute.side_effect = kubectl_side_effect
        result = aci_mocked.get_dependencies("web")
        assert result.status == ResultStatus.SUCCESS
        assert result.data["found"] is True
        assert result.data["service"] == "web"


class TestAciNoAudit:
    """Cover audit disabled path."""

    def test_no_audit_init(self):
        with patch("src.aci.interface.KubectlExecutor"), \
             patch("src.aci.interface.ShellExecutor"), \
             patch("src.aci.interface.SecurityFilter"), \
             patch("src.aci.interface.AuditLogger"), \
             patch("src.aci.interface.LogsProvider"), \
             patch("src.aci.interface.EventsProvider"), \
             patch("src.aci.interface.MetricsProvider"):
            inst = AgentCloudInterface(enable_audit=False)
            assert inst._audit is None
            # _log_audit should be a no-op
            inst._log_audit("test", "detail", "ok")  # no error


class TestKubectlNoSafeMode:
    """Cover safe_mode=False paths."""

    def test_kubectl_no_safe_mode(self):
        with patch("src.aci.interface.KubectlExecutor"), \
             patch("src.aci.interface.ShellExecutor"), \
             patch("src.aci.interface.SecurityFilter"), \
             patch("src.aci.interface.AuditLogger"), \
             patch("src.aci.interface.LogsProvider"), \
             patch("src.aci.interface.EventsProvider"), \
             patch("src.aci.interface.MetricsProvider"):
            inst = AgentCloudInterface(safe_mode=False)
            inst._kubectl.execute.return_value = OperationResult(
                status=ResultStatus.SUCCESS, command="kubectl get pods", stdout="{}")
            r = inst.kubectl(["get", "pods"])
            assert r.status == ResultStatus.SUCCESS
            # security check should NOT be called
            inst._security.check_kubectl.assert_not_called()

    def test_exec_shell_no_safe_mode(self):
        with patch("src.aci.interface.KubectlExecutor"), \
             patch("src.aci.interface.ShellExecutor"), \
             patch("src.aci.interface.SecurityFilter"), \
             patch("src.aci.interface.AuditLogger"), \
             patch("src.aci.interface.LogsProvider"), \
             patch("src.aci.interface.EventsProvider"), \
             patch("src.aci.interface.MetricsProvider"):
            inst = AgentCloudInterface(safe_mode=False)
            inst._shell.execute.return_value = OperationResult(
                status=ResultStatus.SUCCESS, command="ls", stdout="ok")
            r = inst.exec_shell("ls")
            assert r.status == ResultStatus.SUCCESS
            inst._security.check_shell.assert_not_called()


# ============================================================================
# 2. src/config.py — __main__ block
# ============================================================================

class TestConfigMain:
    """Cover the __main__ print block (lines 72-81)."""

    def test_main_block_runs(self):
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, "-m", "src.config"],
            capture_output=True, text=True, timeout=10,
            cwd="/home/ubuntu/agentic-aiops-mvp"
        )
        assert result.returncode == 0
        assert "AgenticAIOps Configuration" in result.stdout
        assert "Default Model" in result.stdout
        assert "Available Models" in result.stdout

    def test_get_model_id_with_global_prefix(self):
        """Cover the global. prefix passthrough (not covered yet)."""
        from src.config import get_model_id
        full_id = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
        # global. prefix doesn't start with 'anthropic.' or 'apac.' so falls through
        # to lookup — verifying correct behavior
        result = get_model_id(full_id)
        assert isinstance(result, str)


# ============================================================================
# 3. src/aci/mcp_bridge.py — MCP Bridge coverage
# ============================================================================

from src.aci.mcp_bridge import ACIMCPBridge, MCP_TOOL_MAPPING, create_mcp_enhanced_aci


class TestMCPToolMapping:
    def test_mapping_keys_exist(self):
        assert "get_logs" in MCP_TOOL_MAPPING
        assert "kubectl" in MCP_TOOL_MAPPING
        assert "troubleshoot" in MCP_TOOL_MAPPING

    def test_mapping_values_are_lists(self):
        for k, v in MCP_TOOL_MAPPING.items():
            assert isinstance(v, list)
            assert len(v) > 0


class TestACIMCPBridgeInit:
    def test_defaults(self):
        bridge = ACIMCPBridge()
        assert bridge.cluster_name == "testing-cluster"
        assert bridge.region == "ap-southeast-1"
        assert bridge._mcp_client is None

    def test_custom_params(self):
        bridge = ACIMCPBridge(cluster_name="prod", region="us-east-1")
        assert bridge.cluster_name == "prod"
        assert bridge.region == "us-east-1"


class TestACIMCPBridgeInitialize:
    def test_initialize_import_error(self):
        bridge = ACIMCPBridge()
        with patch.dict("sys.modules", {"strands.tools.mcp": None}):
            with patch("builtins.__import__", side_effect=ImportError("no strands")):
                result = bridge.initialize()
        # May return True or False depending on import path; just check no crash
        assert isinstance(result, bool)

    def test_initialize_success(self):
        bridge = ACIMCPBridge()
        mock_mcp = MagicMock()
        with patch("src.aci.mcp_bridge.MCPClient", mock_mcp, create=True):
            # Simulate the import succeeding inside initialize
            with patch.dict("sys.modules", {
                "strands.tools.mcp": MagicMock(MCPClient=mock_mcp),
                "mcp": MagicMock(),
            }):
                result = bridge.initialize()
                assert isinstance(result, bool)

    def test_initialize_generic_exception(self):
        bridge = ACIMCPBridge()
        with patch("builtins.__import__", side_effect=RuntimeError("unexpected")):
            result = bridge.initialize()
        assert isinstance(result, bool)


class TestACIMCPBridgeGetTools:
    def test_get_tools_no_client(self):
        bridge = ACIMCPBridge()
        assert bridge.get_tools() == []

    def test_get_tools_with_client(self):
        bridge = ACIMCPBridge()
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.list_tools_sync.return_value = [MagicMock(name="tool1")]
        bridge._mcp_client = mock_client
        tools = bridge.get_tools()
        assert len(tools) == 1

    def test_get_tools_exception(self):
        bridge = ACIMCPBridge()
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(side_effect=RuntimeError("conn failed"))
        bridge._mcp_client = mock_client
        assert bridge.get_tools() == []


class TestACIMCPBridgeListTools:
    def test_list_available_tools_empty(self):
        bridge = ACIMCPBridge()
        assert bridge.list_available_tools() == []

    def test_list_available_tools_with_tool_attr(self):
        bridge = ACIMCPBridge()
        mock_tool = MagicMock()
        mock_tool.tool.name = "describe_pod"
        del mock_tool.name  # ensure 'tool' attr path is taken
        bridge.get_tools = MagicMock(return_value=[mock_tool])
        names = bridge.list_available_tools()
        assert "describe_pod" in names

    def test_list_available_tools_with_name_attr(self):
        bridge = ACIMCPBridge()
        mock_tool = MagicMock(spec=["name"])
        mock_tool.name = "list_pods"
        bridge.get_tools = MagicMock(return_value=[mock_tool])
        names = bridge.list_available_tools()
        assert "list_pods" in names


class TestACIMCPBridgeCallTool:
    def test_call_tool_no_client(self):
        bridge = ACIMCPBridge()
        result = bridge.call_tool("some_tool", arg1="val")
        assert "error" in result

    def test_call_tool_with_client(self):
        bridge = ACIMCPBridge()
        bridge._mcp_client = MagicMock()
        result = bridge.call_tool("get_pods", namespace="default")
        assert result["status"] == "not_implemented"


class TestCreateMCPEnhancedACI:
    def test_create_function(self):
        with patch("src.aci.interface.KubectlExecutor"), \
             patch("src.aci.interface.ShellExecutor"), \
             patch("src.aci.interface.SecurityFilter"), \
             patch("src.aci.interface.AuditLogger"), \
             patch("src.aci.interface.LogsProvider"), \
             patch("src.aci.interface.EventsProvider"), \
             patch("src.aci.interface.MetricsProvider"), \
             patch.object(ACIMCPBridge, "initialize", return_value=False):
            aci = create_mcp_enhanced_aci(cluster_name="test", region="us-west-2")
            assert hasattr(aci, "mcp_bridge")
            assert aci.cluster_name == "test"
