"""
Lambda Plugin — Unit Tests
Covers: LambdaPlugin init, initialize, _discover_functions, health_check,
        get_tools (4 tool funcs), get_resources, get_status_summary
Target: raise src/plugins/lambda_plugin.py coverage from 25% → 70%+
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from src.plugins.base import PluginConfig, PluginStatus
from src.plugins.lambda_plugin import LambdaPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lambda(name="my-func", runtime="python3.12", memory=128,
                 timeout=30, region="ap-southeast-1", code_size=5120):
    return {
        "FunctionName": name,
        "Runtime": runtime,
        "MemorySize": memory,
        "Timeout": timeout,
        "LastModified": "2024-01-15T00:00:00.000+0000",
        "CodeSize": code_size,
    }


def _aws_list_result(functions):
    return MagicMock(
        returncode=0,
        stdout=json.dumps({"Functions": functions}),
        stderr="",
    )


def _aws_fail_result(stderr="AccessDenied"):
    return MagicMock(returncode=1, stdout="", stderr=stderr)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config_single_region():
    return PluginConfig(
        plugin_id="lambda-test",
        plugin_type="lambda",
        name="Test Lambda",
        enabled=True,
        config={"regions": ["ap-southeast-1"]},
    )


@pytest.fixture
def config_multi_region():
    return PluginConfig(
        plugin_id="lambda-multi",
        plugin_type="lambda",
        name="Multi Lambda",
        enabled=True,
        config={"regions": ["ap-southeast-1", "us-east-1"]},
    )


@pytest.fixture
def config_no_regions():
    """Config without explicit regions → defaults to ['ap-southeast-1']."""
    return PluginConfig(
        plugin_id="lambda-default",
        plugin_type="lambda",
        name="Default Lambda",
        enabled=True,
        config={},
    )


@pytest.fixture
def plugin(config_single_region):
    return LambdaPlugin(config_single_region)


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------

class TestInit:
    def test_default_regions(self, config_no_regions):
        p = LambdaPlugin(config_no_regions)
        assert p.regions == ["ap-southeast-1"]
        assert p.functions == []
        assert p.status == PluginStatus.DISABLED

    def test_custom_regions(self, config_multi_region):
        p = LambdaPlugin(config_multi_region)
        assert p.regions == ["ap-southeast-1", "us-east-1"]


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------

class TestInitialize:
    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_initialize_success(self, mock_run, plugin):
        mock_run.return_value = _aws_list_result([_make_lambda()])
        assert plugin.initialize() is True
        assert plugin.status == PluginStatus.ENABLED
        assert len(plugin.functions) == 1

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_initialize_fail_exception(self, mock_run, plugin):
        """Exception inside _discover_functions is caught there, so initialize
        still succeeds (empty list). To trigger actual failure in initialize,
        we need to break _discover_functions at a higher level."""
        mock_run.side_effect = Exception("boom")
        # _discover_functions catches per-region exceptions, so initialize succeeds
        assert plugin.initialize() is True
        assert plugin.functions == []

    @patch.object(LambdaPlugin, "_discover_functions", side_effect=Exception("fatal"))
    def test_initialize_discover_raises(self, mock_discover, plugin):
        """If _discover_functions itself raises, initialize returns False."""
        assert plugin.initialize() is False
        assert plugin.status == PluginStatus.ERROR


# ---------------------------------------------------------------------------
# _discover_functions
# ---------------------------------------------------------------------------

class TestDiscoverFunctions:
    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_single_region(self, mock_run, plugin):
        funcs = [_make_lambda("func-a"), _make_lambda("func-b")]
        mock_run.return_value = _aws_list_result(funcs)

        plugin._discover_functions()
        assert len(plugin.functions) == 2
        assert plugin.functions[0]["function_name"] == "func-a"
        assert plugin.functions[0]["region"] == "ap-southeast-1"

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_multi_region(self, mock_run, config_multi_region):
        p = LambdaPlugin(config_multi_region)
        mock_run.side_effect = [
            _aws_list_result([_make_lambda("func-ap")]),
            _aws_list_result([_make_lambda("func-us")]),
        ]
        p._discover_functions()
        assert len(p.functions) == 2
        names = {f["function_name"] for f in p.functions}
        assert names == {"func-ap", "func-us"}

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_returncode_nonzero_skips(self, mock_run, plugin):
        mock_run.return_value = _aws_fail_result()
        plugin._discover_functions()
        assert plugin.functions == []

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_exception_in_region_skips(self, mock_run, plugin):
        mock_run.side_effect = Exception("network error")
        plugin._discover_functions()
        assert plugin.functions == []

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_empty_functions_list(self, mock_run, plugin):
        mock_run.return_value = _aws_list_result([])
        plugin._discover_functions()
        assert plugin.functions == []


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_health_check_empty(self, plugin):
        result = plugin.health_check()
        assert result["healthy"] is True
        assert result["total_functions"] == 0

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_health_check_with_functions(self, mock_run, plugin):
        mock_run.return_value = _aws_list_result([_make_lambda()])
        plugin._discover_functions()
        result = plugin.health_check()
        assert result["total_functions"] == 1


# ---------------------------------------------------------------------------
# get_resources / get_status_summary
# ---------------------------------------------------------------------------

class TestResourcesAndSummary:
    def test_get_resources_empty(self, plugin):
        assert plugin.get_resources() == []

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_get_resources_populated(self, mock_run, plugin):
        mock_run.return_value = _aws_list_result([_make_lambda("r-func")])
        plugin._discover_functions()
        res = plugin.get_resources()
        assert len(res) == 1
        assert res[0]["function_name"] == "r-func"

    def test_get_status_summary_empty(self, plugin):
        s = plugin.get_status_summary()
        assert s["plugin_type"] == "lambda"
        assert s["icon"] == "λ"
        assert s["total_functions"] == 0
        assert s["functions"] == []

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_get_status_summary_capped_at_10(self, mock_run, plugin):
        funcs = [_make_lambda(f"f-{i}") for i in range(15)]
        mock_run.return_value = _aws_list_result(funcs)
        plugin._discover_functions()
        s = plugin.get_status_summary()
        assert s["total_functions"] == 15
        assert len(s["functions"]) == 10


# ---------------------------------------------------------------------------
# get_tools – test the 4 inner tool callables
# ---------------------------------------------------------------------------

class TestGetTools:
    """Test each tool function returned by get_tools()."""

    def _get_tool_map(self, plugin):
        tools = plugin.get_tools()
        assert len(tools) == 4
        return {t.__name__: t for t in tools}

    # ---- lambda_list_functions ----

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_list_functions_no_functions(self, mock_run, plugin):
        mock_run.return_value = _aws_list_result([])
        tool_fn = self._get_tool_map(plugin)["lambda_list_functions"]
        result = tool_fn(region=None)
        assert "No Lambda functions found" in result

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_list_functions_with_data(self, mock_run, plugin):
        mock_run.return_value = _aws_list_result([_make_lambda("hello-world", code_size=10240)])
        tool_fn = self._get_tool_map(plugin)["lambda_list_functions"]
        result = tool_fn(region=None)
        assert "hello-world" in result
        assert "Lambda Functions:" in result

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_list_functions_region_filter(self, mock_run, config_multi_region):
        p = LambdaPlugin(config_multi_region)
        mock_run.side_effect = [
            _aws_list_result([_make_lambda("ap-func")]),
            _aws_list_result([_make_lambda("us-func")]),
        ]
        tool_fn = [t for t in p.get_tools() if t.__name__ == "lambda_list_functions"][0]
        # Now mock the refresh call inside the tool
        mock_run.side_effect = [
            _aws_list_result([_make_lambda("ap-func")]),
            _aws_list_result([_make_lambda("us-func")]),
        ]
        result = tool_fn(region="us-east-1")
        assert "us-func" in result

    # ---- lambda_get_function_config ----

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_get_function_config_success(self, mock_run, plugin):
        config_data = {
            "Runtime": "python3.12",
            "MemorySize": 256,
            "Timeout": 30,
            "Handler": "index.handler",
            "Role": "arn:aws:iam::role/lambda",
            "LastModified": "2024-01-01T00:00:00Z",
            "Environment": {"Variables": {"DB_HOST": "localhost", "DEBUG": "1"}},
        }
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(config_data), stderr="")
        tool_fn = self._get_tool_map(plugin)["lambda_get_function_config"]
        result = tool_fn(function_name="my-func", region="ap-southeast-1")
        assert "Lambda Function: my-func" in result
        assert "python3.12" in result
        assert "DB_HOST" in result

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_get_function_config_error_returncode(self, mock_run, plugin):
        mock_run.return_value = _aws_fail_result("not found")
        tool_fn = self._get_tool_map(plugin)["lambda_get_function_config"]
        result = tool_fn(function_name="bad", region="ap-southeast-1")
        assert "Error:" in result

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_get_function_config_exception(self, mock_run, plugin):
        mock_run.side_effect = Exception("timeout")
        tool_fn = self._get_tool_map(plugin)["lambda_get_function_config"]
        result = tool_fn(function_name="bad", region="ap-southeast-1")
        assert "Error:" in result

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_get_function_config_no_env(self, mock_run, plugin):
        config_data = {
            "Runtime": "nodejs18.x",
            "MemorySize": 128,
            "Timeout": 10,
            "Handler": "index.handler",
            "Role": "arn:aws:iam::role/x",
            "LastModified": "2024-06-01",
        }
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(config_data), stderr="")
        tool_fn = self._get_tool_map(plugin)["lambda_get_function_config"]
        result = tool_fn(function_name="no-env", region="ap-southeast-1")
        assert "Environment" not in result

    # ---- lambda_get_invocations ----

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_get_invocations_with_data(self, mock_run, plugin):
        cw_data = {
            "Datapoints": [
                {"Timestamp": "2024-01-15T10:00:00Z", "Sum": 50},
                {"Timestamp": "2024-01-15T10:05:00Z", "Sum": 30},
            ]
        }
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(cw_data), stderr="")
        tool_fn = self._get_tool_map(plugin)["lambda_get_invocations"]
        result = tool_fn(function_name="my-func", region="ap-southeast-1")
        assert "Total: 80" in result
        assert "Invocations for my-func" in result

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_get_invocations_no_data(self, mock_run, plugin):
        cw_data = {"Datapoints": []}
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(cw_data), stderr="")
        tool_fn = self._get_tool_map(plugin)["lambda_get_invocations"]
        result = tool_fn(function_name="my-func", region="ap-southeast-1")
        assert "No invocation data" in result

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_get_invocations_error(self, mock_run, plugin):
        mock_run.return_value = _aws_fail_result("cw error")
        tool_fn = self._get_tool_map(plugin)["lambda_get_invocations"]
        result = tool_fn(function_name="my-func", region="ap-southeast-1")
        assert "Error:" in result

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_get_invocations_exception(self, mock_run, plugin):
        mock_run.side_effect = Exception("boom")
        tool_fn = self._get_tool_map(plugin)["lambda_get_invocations"]
        result = tool_fn(function_name="my-func", region="ap-southeast-1")
        assert "Error:" in result

    # ---- lambda_get_errors ----

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_get_errors_with_errors(self, mock_run, plugin):
        cw_data = {
            "Datapoints": [
                {"Timestamp": "2024-01-15T10:00:00Z", "Sum": 5},
                {"Timestamp": "2024-01-15T10:05:00Z", "Sum": 3},
            ]
        }
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(cw_data), stderr="")
        tool_fn = self._get_tool_map(plugin)["lambda_get_errors"]
        result = tool_fn(function_name="my-func", region="ap-southeast-1")
        assert "Total Errors: 8" in result
        assert "⚠️" in result

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_get_errors_no_errors(self, mock_run, plugin):
        cw_data = {
            "Datapoints": [
                {"Timestamp": "2024-01-15T10:00:00Z", "Sum": 0},
            ]
        }
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(cw_data), stderr="")
        tool_fn = self._get_tool_map(plugin)["lambda_get_errors"]
        result = tool_fn(function_name="my-func", region="ap-southeast-1")
        assert "No errors" in result
        assert "✅" in result

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_get_errors_empty_datapoints(self, mock_run, plugin):
        cw_data = {"Datapoints": []}
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(cw_data), stderr="")
        tool_fn = self._get_tool_map(plugin)["lambda_get_errors"]
        result = tool_fn(function_name="my-func", region="ap-southeast-1")
        assert "No errors" in result

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_get_errors_aws_error(self, mock_run, plugin):
        mock_run.return_value = _aws_fail_result("denied")
        tool_fn = self._get_tool_map(plugin)["lambda_get_errors"]
        result = tool_fn(function_name="my-func", region="ap-southeast-1")
        assert "Error:" in result

    @patch("src.plugins.lambda_plugin.subprocess.run")
    def test_get_errors_exception(self, mock_run, plugin):
        mock_run.side_effect = Exception("oops")
        tool_fn = self._get_tool_map(plugin)["lambda_get_errors"]
        result = tool_fn(function_name="my-func", region="ap-southeast-1")
        assert "Error:" in result
