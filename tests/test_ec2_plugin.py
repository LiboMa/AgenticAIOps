"""
EC2 Plugin — Unit Tests
Covers: EC2Plugin init, health_check, get_tools, get_resources, get_status_summary, _discover_instances
Target: raise src/plugins/ec2_plugin.py coverage from 25% → 75%+
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from src.plugins.base import PluginConfig, PluginStatus
from src.plugins.ec2_plugin import EC2Plugin


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ec2_config():
    return PluginConfig(
        plugin_id="ec2-test",
        plugin_type="ec2",
        name="Test EC2",
        enabled=True,
        config={"regions": ["us-east-1"]},
    )


@pytest.fixture
def plugin(ec2_config):
    return EC2Plugin(ec2_config)


def _describe_instances_result(instances_by_reservation):
    """Build mock for aws ec2 describe-instances. instances_by_reservation is a list of lists."""
    reservations = []
    for inst_list in instances_by_reservation:
        reservations.append({"Instances": inst_list})
    return MagicMock(
        returncode=0,
        stdout=json.dumps({"Reservations": reservations}),
        stderr="",
    )


def _make_instance(instance_id="i-abc123", name="web-server", state="running",
                   itype="m5.large", private_ip="10.0.0.1", public_ip="54.1.2.3"):
    inst = {
        "InstanceId": instance_id,
        "State": {"Name": state},
        "InstanceType": itype,
        "PrivateIpAddress": private_ip,
        "PublicIpAddress": public_ip,
        "Tags": [{"Key": "Name", "Value": name}],
    }
    return inst


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestEC2PluginInit:

    def test_default_regions(self):
        cfg = PluginConfig(plugin_id="x", plugin_type="ec2", name="X", config={})
        p = EC2Plugin(cfg)
        assert p.regions == ["ap-southeast-1"]

    @patch("src.plugins.ec2_plugin.subprocess.run")
    def test_initialize_success(self, mock_run, ec2_config):
        mock_run.return_value = _describe_instances_result([
            [_make_instance()]
        ])
        p = EC2Plugin(ec2_config)
        assert p.initialize() is True
        assert p.status == PluginStatus.ENABLED
        assert len(p.instances) == 1

    @patch("src.plugins.ec2_plugin.subprocess.run")
    def test_initialize_with_discovery_exception(self, mock_run, ec2_config):
        """_discover_instances catches per-region exceptions, so initialize still succeeds."""
        mock_run.side_effect = Exception("boom")
        p = EC2Plugin(ec2_config)
        assert p.initialize() is True
        assert p.status == PluginStatus.ENABLED
        assert len(p.instances) == 0

    @patch.object(EC2Plugin, "_discover_instances", side_effect=Exception("catastrophic"))
    def test_initialize_failure(self, mock_discover, ec2_config):
        """If _discover_instances itself raises, initialize returns False."""
        p = EC2Plugin(ec2_config)
        assert p.initialize() is False
        assert p.status == PluginStatus.ERROR


# ---------------------------------------------------------------------------
# _discover_instances
# ---------------------------------------------------------------------------

class TestDiscoverInstances:

    @patch("src.plugins.ec2_plugin.subprocess.run")
    def test_discover_parses_instances(self, mock_run, plugin):
        mock_run.return_value = _describe_instances_result([
            [
                _make_instance("i-001", "web", "running", "m5.large", "10.0.0.1", "54.1.1.1"),
                _make_instance("i-002", "db", "stopped", "r5.large", "10.0.0.2", None),
            ]
        ])

        plugin._discover_instances()

        assert len(plugin.instances) == 2
        assert plugin.instances[0]["instance_id"] == "i-001"
        assert plugin.instances[0]["name"] == "web"
        assert plugin.instances[0]["state"] == "running"
        assert plugin.instances[1]["public_ip"] is None

    @patch("src.plugins.ec2_plugin.subprocess.run")
    def test_discover_no_name_tag(self, mock_run, plugin):
        """Instance without Name tag gets 'unnamed'."""
        inst = _make_instance()
        inst["Tags"] = []  # no Name tag
        mock_run.return_value = _describe_instances_result([[inst]])

        plugin._discover_instances()

        assert plugin.instances[0]["name"] == "unnamed"

    @patch("src.plugins.ec2_plugin.subprocess.run")
    def test_discover_no_tags(self, mock_run, plugin):
        """Instance without Tags key at all."""
        inst = _make_instance()
        del inst["Tags"]
        mock_run.return_value = _describe_instances_result([[inst]])

        plugin._discover_instances()

        assert plugin.instances[0]["name"] == "unnamed"

    @patch("src.plugins.ec2_plugin.subprocess.run")
    def test_discover_cli_error(self, mock_run, plugin):
        """CLI failure is handled gracefully."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="access denied")

        plugin._discover_instances()

        assert plugin.instances == []

    @patch("src.plugins.ec2_plugin.subprocess.run")
    def test_discover_exception(self, mock_run, plugin):
        mock_run.side_effect = Exception("timeout")

        plugin._discover_instances()

        assert plugin.instances == []

    @patch("src.plugins.ec2_plugin.subprocess.run")
    def test_multi_region(self, mock_run):
        cfg = PluginConfig(
            plugin_id="mr", plugin_type="ec2", name="MR",
            config={"regions": ["us-east-1", "eu-west-1"]},
        )
        p = EC2Plugin(cfg)

        r1 = _describe_instances_result([[_make_instance("i-us", "us-box")]])
        r2 = _describe_instances_result([[_make_instance("i-eu", "eu-box")]])
        mock_run.side_effect = [r1, r2]

        p._discover_instances()

        assert len(p.instances) == 2
        ids = {i["instance_id"] for i in p.instances}
        assert ids == {"i-us", "i-eu"}

    @patch("src.plugins.ec2_plugin.subprocess.run")
    def test_discover_clears_old(self, mock_run, plugin):
        """Each call resets the instance list."""
        plugin.instances = [{"old": True}]
        mock_run.return_value = _describe_instances_result([])

        plugin._discover_instances()

        assert plugin.instances == []


# ---------------------------------------------------------------------------
# health_check / get_resources / get_status_summary
# ---------------------------------------------------------------------------

class TestEC2PluginMethods:

    def test_health_check_empty(self, plugin):
        h = plugin.health_check()
        assert h["healthy"] is True
        assert h["total_instances"] == 0
        assert h["running_instances"] == 0

    def test_health_check_with_instances(self, plugin):
        plugin.instances = [
            {"state": "running"}, {"state": "running"}, {"state": "stopped"},
        ]
        h = plugin.health_check()
        assert h["total_instances"] == 3
        assert h["running_instances"] == 2
        assert h["stopped_instances"] == 1

    def test_get_resources(self, plugin):
        plugin.instances = [{"x": 1}]
        assert plugin.get_resources() == [{"x": 1}]

    def test_get_status_summary(self, plugin):
        plugin.instances = [
            {"state": "running", "instance_id": "i-1", "name": "a", "region": "us-east-1",
             "type": "m5.large", "private_ip": "10.0.0.1", "public_ip": None},
        ]
        s = plugin.get_status_summary()
        assert s["plugin_type"] == "ec2"
        assert s["icon"] == "🖥️"
        assert s["running"] == 1
        assert s["stopped"] == 0
        assert len(s["instances"]) == 1

    def test_get_status_summary_truncates_to_10(self, plugin):
        plugin.instances = [{"state": "running"} for _ in range(15)]
        s = plugin.get_status_summary()
        assert len(s["instances"]) == 10


# ---------------------------------------------------------------------------
# get_tools
# ---------------------------------------------------------------------------

class TestEC2PluginTools:

    def test_tools_returned(self, plugin):
        tools = plugin.get_tools()
        names = [t.__name__ for t in tools]
        assert "ec2_list_instances" in names
        assert "ec2_get_instance_status" in names
        assert "ec2_get_metrics" in names

    @patch("src.plugins.ec2_plugin.subprocess.run")
    def test_ec2_list_instances_tool(self, mock_run, plugin):
        mock_run.return_value = _describe_instances_result([
            [_make_instance("i-1", "web", "running")]
        ])
        tools = plugin.get_tools()
        list_fn = next(t for t in tools if t.__name__ == "ec2_list_instances")

        result = list_fn()

        assert "web" in result
        assert "i-1" in result

    @patch("src.plugins.ec2_plugin.subprocess.run")
    def test_ec2_list_instances_empty(self, mock_run, plugin):
        mock_run.return_value = _describe_instances_result([])
        tools = plugin.get_tools()
        list_fn = next(t for t in tools if t.__name__ == "ec2_list_instances")

        result = list_fn()

        assert "No EC2 instances found" in result

    @patch("src.plugins.ec2_plugin.subprocess.run")
    def test_ec2_list_filter_by_state(self, mock_run, plugin):
        mock_run.return_value = _describe_instances_result([
            [
                _make_instance("i-1", "web", "running"),
                _make_instance("i-2", "db", "stopped"),
            ]
        ])
        tools = plugin.get_tools()
        list_fn = next(t for t in tools if t.__name__ == "ec2_list_instances")

        result = list_fn(state="stopped")

        assert "db" in result
        assert "web" not in result

    @patch("src.plugins.ec2_plugin.subprocess.run")
    def test_ec2_get_instance_status_success(self, mock_run, plugin):
        """Instance status from pre-populated list uses correct region."""
        plugin.instances = [{"instance_id": "i-123", "region": "us-east-1"}]
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "InstanceStatuses": [{
                    "InstanceState": {"Name": "running"},
                    "SystemStatus": {"Status": "ok"},
                }]
            }),
            stderr="",
        )
        tools = plugin.get_tools()
        status_fn = next(t for t in tools if t.__name__ == "ec2_get_instance_status")

        result = status_fn(instance_id="i-123")

        assert "running" in result

    @patch("src.plugins.ec2_plugin.subprocess.run")
    def test_ec2_get_instance_status_empty(self, mock_run, plugin):
        """Stopped instance returns 'not available'."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"InstanceStatuses": []}),
            stderr="",
        )
        tools = plugin.get_tools()
        status_fn = next(t for t in tools if t.__name__ == "ec2_get_instance_status")

        result = status_fn(instance_id="i-stopped")

        assert "not available" in result

    @patch("src.plugins.ec2_plugin.subprocess.run")
    def test_ec2_get_instance_status_error(self, mock_run, plugin):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not found")

        tools = plugin.get_tools()
        status_fn = next(t for t in tools if t.__name__ == "ec2_get_instance_status")

        result = status_fn(instance_id="i-bad")

        assert "Error" in result

    @patch("src.plugins.ec2_plugin.subprocess.run")
    def test_ec2_get_instance_status_exception(self, mock_run, plugin):
        mock_run.side_effect = Exception("network error")

        tools = plugin.get_tools()
        status_fn = next(t for t in tools if t.__name__ == "ec2_get_instance_status")

        result = status_fn(instance_id="i-x")

        assert "Error" in result

    @patch("src.plugins.ec2_plugin.subprocess.run")
    def test_ec2_get_metrics_success(self, mock_run, plugin):
        plugin.instances = [{"instance_id": "i-123", "region": "us-east-1"}]
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "Datapoints": [
                    {"Timestamp": "2026-02-25T02:55:00Z", "Average": 12.5},
                    {"Timestamp": "2026-02-25T03:00:00Z", "Average": 15.3},
                ]
            }),
            stderr="",
        )
        tools = plugin.get_tools()
        metrics_fn = next(t for t in tools if t.__name__ == "ec2_get_metrics")

        result = metrics_fn(instance_id="i-123")

        assert "CPUUtilization" in result
        assert "12.50" in result

    @patch("src.plugins.ec2_plugin.subprocess.run")
    def test_ec2_get_metrics_no_data(self, mock_run, plugin):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"Datapoints": []}),
            stderr="",
        )
        tools = plugin.get_tools()
        metrics_fn = next(t for t in tools if t.__name__ == "ec2_get_metrics")

        result = metrics_fn(instance_id="i-123")

        assert "No" in result and "data available" in result

    @patch("src.plugins.ec2_plugin.subprocess.run")
    def test_ec2_get_metrics_error(self, mock_run, plugin):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="access denied")

        tools = plugin.get_tools()
        metrics_fn = next(t for t in tools if t.__name__ == "ec2_get_metrics")

        result = metrics_fn(instance_id="i-123")

        assert "Error" in result

    @patch("src.plugins.ec2_plugin.subprocess.run")
    def test_ec2_get_metrics_exception(self, mock_run, plugin):
        mock_run.side_effect = Exception("boom")

        tools = plugin.get_tools()
        metrics_fn = next(t for t in tools if t.__name__ == "ec2_get_metrics")

        result = metrics_fn(instance_id="i-123")

        assert "Error" in result

    @patch("src.plugins.ec2_plugin.subprocess.run")
    def test_ec2_get_metrics_custom_metric(self, mock_run, plugin):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "Datapoints": [
                    {"Timestamp": "2026-02-25T03:00:00Z", "Average": 1024.0},
                ]
            }),
            stderr="",
        )
        tools = plugin.get_tools()
        metrics_fn = next(t for t in tools if t.__name__ == "ec2_get_metrics")

        result = metrics_fn(instance_id="i-123", metric="NetworkIn", period=60)

        assert "NetworkIn" in result
