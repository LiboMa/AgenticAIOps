"""
Daily Coverage Boost — 2026-03-16

Targets the 3 lowest-coverage modules:
  1. src/aws_scanner.py (74%) — IAM, Route53, DynamoDB, ECS, ElastiCache, EKS, CloudWatch alarms
  2. src/chaos/scenarios.py (77%) — PodKill, ConfigBreak, NodeDrain scenarios
  3. src/issues/manager.py (77%) — list_issues, get_issue, _classify_severity edge cases
"""

import json
import subprocess
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from botocore.exceptions import ClientError


# ---------------------------------------------------------------------------
# 1. aws_scanner — cover missing scan methods
# ---------------------------------------------------------------------------
class TestAWSScanner:
    """Cover previously-untested scan_* methods in AWSCloudScanner."""

    @pytest.fixture
    def scanner(self):
        from src.aws_scanner import AWSCloudScanner
        s = AWSCloudScanner(region="us-east-1")
        s._session = MagicMock()
        return s

    # --- _scan_iam ---
    def test_scan_iam_success(self, scanner):
        mock_iam = MagicMock()
        mock_iam.list_users.return_value = {
            "Users": [
                {"UserName": "alice"},
                {"UserName": "bob"},
            ]
        }
        mock_iam.list_roles.return_value = {"Roles": [{"RoleName": "admin"}]}
        # alice has MFA, bob does not
        mock_iam.list_mfa_devices.side_effect = [
            {"MFADevices": [{"SerialNumber": "arn:aws:iam::mfa/alice"}]},
            {"MFADevices": []},
        ]
        scanner._session.client.return_value = mock_iam

        result = scanner._scan_iam()
        assert result["users_count"] == 2
        assert result["roles_count"] == 1
        assert "bob" in result["users_without_mfa"]
        assert "alice" not in result["users_without_mfa"]

    def test_scan_iam_error(self, scanner):
        mock_iam = MagicMock()
        mock_iam.list_users.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "nope"}}, "ListUsers"
        )
        scanner._session.client.return_value = mock_iam

        result = scanner._scan_iam()
        assert "error" in result

    # --- _scan_route53 ---
    def test_scan_route53_success(self, scanner):
        mock_r53 = MagicMock()
        mock_r53.list_hosted_zones.return_value = {
            "HostedZones": [
                {
                    "Id": "/hostedzone/Z123",
                    "Name": "example.com.",
                    "Config": {"PrivateZone": False},
                    "ResourceRecordSetCount": 10,
                }
            ]
        }
        mock_r53.list_health_checks.return_value = {
            "HealthChecks": [{"Id": "hc-1"}]
        }
        scanner._session.client.return_value = mock_r53

        result = scanner._scan_route53()
        assert result["count"] == 1
        assert result["health_checks_count"] == 1
        assert result["hosted_zones"][0]["name"] == "example.com."

    def test_scan_route53_error(self, scanner):
        mock_r53 = MagicMock()
        mock_r53.list_hosted_zones.side_effect = ClientError(
            {"Error": {"Code": "Throttling", "Message": "slow"}}, "ListHostedZones"
        )
        scanner._session.client.return_value = mock_r53

        result = scanner._scan_route53()
        assert "error" in result

    # --- _scan_dynamodb ---
    def test_scan_dynamodb_success(self, scanner):
        mock_ddb = MagicMock()
        mock_ddb.list_tables.return_value = {"TableNames": ["orders", "users"]}
        mock_ddb.describe_table.side_effect = [
            {
                "Table": {
                    "TableStatus": "ACTIVE",
                    "BillingModeSummary": {"BillingMode": "PAY_PER_REQUEST"},
                    "ProvisionedThroughput": {},
                    "ItemCount": 500,
                }
            },
            {
                "Table": {
                    "TableStatus": "ACTIVE",
                    "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
                    "ItemCount": 200,
                }
            },
        ]
        scanner._session.client.return_value = mock_ddb

        result = scanner._scan_dynamodb()
        assert result["count"] == 2
        assert result["tables"][0]["billing_mode"] == "PAY_PER_REQUEST"
        assert result["tables"][1]["read_capacity"] == 5

    def test_scan_dynamodb_describe_error(self, scanner):
        """When describe_table fails for one table, it should still show ERROR."""
        mock_ddb = MagicMock()
        mock_ddb.list_tables.return_value = {"TableNames": ["broken"]}
        mock_ddb.describe_table.side_effect = Exception("boom")
        scanner._session.client.return_value = mock_ddb

        result = scanner._scan_dynamodb()
        assert result["count"] == 1
        assert result["tables"][0]["status"] == "ERROR"

    # --- _scan_ecs ---
    def test_scan_ecs_success(self, scanner):
        mock_ecs = MagicMock()
        mock_ecs.list_clusters.return_value = {"clusterArns": ["arn:aws:ecs:us-east-1:123:cluster/prod"]}
        mock_ecs.describe_clusters.return_value = {
            "clusters": [
                {
                    "clusterName": "prod",
                    "status": "ACTIVE",
                    "runningTasksCount": 5,
                    "registeredContainerInstancesCount": 2,
                }
            ]
        }
        scanner._session.client.return_value = mock_ecs

        result = scanner._scan_ecs()
        assert result["count"] == 1
        assert result["clusters"][0]["name"] == "prod"
        assert result["clusters"][0]["running_tasks"] == 5

    def test_scan_ecs_error(self, scanner):
        mock_ecs = MagicMock()
        mock_ecs.list_clusters.side_effect = ClientError(
            {"Error": {"Code": "ClusterNotFoundException", "Message": "gone"}}, "ListClusters"
        )
        scanner._session.client.return_value = mock_ecs

        result = scanner._scan_ecs()
        assert "error" in result

    # --- _scan_elasticache ---
    def test_scan_elasticache_success(self, scanner):
        mock_ec = MagicMock()
        mock_ec.describe_cache_clusters.return_value = {
            "CacheClusters": [
                {
                    "CacheClusterId": "redis-01",
                    "Engine": "redis",
                    "EngineVersion": "7.0",
                    "CacheClusterStatus": "available",
                    "CacheNodeType": "cache.t3.micro",
                    "NumCacheNodes": 1,
                }
            ]
        }
        mock_ec.describe_replication_groups.return_value = {
            "ReplicationGroups": [
                {
                    "ReplicationGroupId": "rg-01",
                    "Status": "available",
                    "MemberClusters": ["redis-01", "redis-02"],
                }
            ]
        }
        scanner._session.client.return_value = mock_ec

        result = scanner._scan_elasticache()
        assert result["count"] == 2  # 1 cluster + 1 replication group
        assert result["clusters"][0]["engine"] == "redis"
        assert result["clusters"][1]["type"] == "replication_group"
        assert result["clusters"][1]["num_nodes"] == 2

    def test_scan_elasticache_replication_error(self, scanner):
        """Replication group call fails but cache clusters still returned."""
        mock_ec = MagicMock()
        mock_ec.describe_cache_clusters.return_value = {"CacheClusters": []}
        mock_ec.describe_replication_groups.side_effect = Exception("timeout")
        scanner._session.client.return_value = mock_ec

        result = scanner._scan_elasticache()
        assert result["count"] == 0

    # --- _scan_eks ---
    def test_scan_eks_success(self, scanner):
        mock_eks = MagicMock()
        mock_eks.list_clusters.return_value = {"clusters": ["prod-cluster"]}
        mock_eks.describe_cluster.return_value = {
            "cluster": {
                "version": "1.28",
                "status": "ACTIVE",
                "endpoint": "https://eks.example.com",
            }
        }
        scanner._session.client.return_value = mock_eks

        result = scanner._scan_eks()
        assert result["count"] == 1
        assert result["clusters"][0]["version"] == "1.28"

    def test_scan_eks_describe_error(self, scanner):
        """describe_cluster fails, should still list the cluster name."""
        mock_eks = MagicMock()
        mock_eks.list_clusters.return_value = {"clusters": ["broken-cluster"]}
        mock_eks.describe_cluster.side_effect = Exception("API error")
        scanner._session.client.return_value = mock_eks

        result = scanner._scan_eks()
        assert result["count"] == 1
        assert result["clusters"][0]["name"] == "broken-cluster"

    # --- _scan_cloudwatch_alarms ---
    def test_scan_cloudwatch_alarms_success(self, scanner):
        mock_cw = MagicMock()
        mock_cw.describe_alarms.return_value = {
            "MetricAlarms": [
                {
                    "AlarmName": "HighCPU",
                    "StateValue": "ALARM",
                    "MetricName": "CPUUtilization",
                    "Namespace": "AWS/EC2",
                },
                {
                    "AlarmName": "LowDisk",
                    "StateValue": "OK",
                    "MetricName": "DiskUsage",
                    "Namespace": "AWS/EC2",
                },
            ]
        }
        scanner._session.client.return_value = mock_cw

        result = scanner._scan_cloudwatch_alarms()
        assert result["count"] == 2
        assert result["by_state"]["ALARM"] == 1
        assert result["by_state"]["OK"] == 1

    def test_scan_cloudwatch_alarms_error(self, scanner):
        mock_cw = MagicMock()
        mock_cw.describe_alarms.side_effect = ClientError(
            {"Error": {"Code": "InternalError", "Message": "oops"}}, "DescribeAlarms"
        )
        scanner._session.client.return_value = mock_cw

        result = scanner._scan_cloudwatch_alarms()
        assert "error" in result

    # --- _scan_s3 with public bucket detection ---
    def test_scan_s3_public_bucket(self, scanner):
        mock_s3 = MagicMock()
        mock_s3.list_buckets.return_value = {
            "Buckets": [
                {"Name": "public-bucket", "CreationDate": datetime(2025, 1, 1, tzinfo=timezone.utc)},
            ]
        }
        mock_s3.get_bucket_acl.return_value = {
            "Grants": [
                {
                    "Grantee": {"URI": "http://acs.amazonaws.com/groups/global/AllUsers"},
                    "Permission": "READ",
                }
            ]
        }
        scanner._session.client.return_value = mock_s3

        result = scanner._scan_s3()
        assert result["public_count"] == 1
        assert result["buckets"][0]["public"] is True

    # --- _generate_summary cloudwatch alarm branch ---
    def test_generate_summary_cloudwatch_alarms(self, scanner):
        services = {
            "ec2": {"count": 3, "status": {"running": 3, "stopped": 0}},
            "cloudwatch": {"count": 2, "by_state": {"OK": 1, "ALARM": 1, "INSUFFICIENT_DATA": 0}},
        }
        summary = scanner._generate_summary(services)
        alarm_issues = [i for i in summary["issues_found"] if i["type"] == "active_alarms"]
        assert len(alarm_issues) == 1
        assert alarm_issues[0]["count"] == 1


# ---------------------------------------------------------------------------
# 2. chaos/scenarios — PodKill, ConfigBreak, NodeDrain
# ---------------------------------------------------------------------------
class TestChaosScenarios:
    """Cover untested scenario classes and edge cases."""

    @patch("src.chaos.scenarios._run_kubectl")
    def test_pod_kill_execute_kill(self, mock_kubectl):
        from src.chaos.scenarios import PodKillScenario
        mock_kubectl.return_value = MagicMock(
            returncode=0, stdout="pod deleted", stderr=""
        )
        scenario = PodKillScenario()
        obs = scenario.execute("default", {"action": "kill", "target_label": "app=web"})
        assert any("Force-deleted" in o for o in obs)
        mock_kubectl.assert_called_once()
        args = mock_kubectl.call_args[0][0]
        assert "-l" in args and "app=web" in args

    @patch("src.chaos.scenarios._run_kubectl")
    def test_pod_kill_execute_scale_zero(self, mock_kubectl):
        from src.chaos.scenarios import PodKillScenario
        mock_kubectl.return_value = MagicMock(returncode=0, stdout="scaled", stderr="")
        scenario = PodKillScenario()
        obs = scenario.execute("default", {"action": "scale-zero", "deployments": ["api", "worker"]})
        assert len(obs) == 2
        assert mock_kubectl.call_count == 2

    @patch("src.chaos.scenarios._run_kubectl")
    def test_pod_kill_rollback(self, mock_kubectl):
        from src.chaos.scenarios import PodKillScenario
        mock_kubectl.return_value = MagicMock(returncode=0, stdout="", stderr="")
        scenario = PodKillScenario()
        obs = scenario.rollback("default", {"original_replicas": {"api": 2}})
        assert any("Restored" in o for o in obs)

    @patch("src.chaos.scenarios._run_kubectl")
    def test_pod_kill_rollback_failure(self, mock_kubectl):
        from src.chaos.scenarios import PodKillScenario
        mock_kubectl.return_value = MagicMock(returncode=1, stdout="", stderr="not found")
        scenario = PodKillScenario()
        obs = scenario.rollback("default", {"original_replicas": {"api": 2}})
        assert any("Failed" in o for o in obs)

    @patch("src.chaos.scenarios._run_kubectl")
    @patch("subprocess.run")
    def test_config_break_bad_image(self, mock_subrun, mock_kubectl):
        from src.chaos.scenarios import ConfigBreakScenario
        mock_kubectl.return_value = MagicMock(returncode=0, stdout="image updated", stderr="")
        scenario = ConfigBreakScenario()
        obs = scenario.execute("prod", {"action": "bad-image", "bad_image": "nginx:broken"})
        assert any("ImagePullBackOff" in o for o in obs)

    @patch("src.chaos.scenarios._run_kubectl")
    @patch("subprocess.run")
    def test_config_break_bad_config(self, mock_subrun, mock_kubectl):
        from src.chaos.scenarios import ConfigBreakScenario
        mock_subrun.return_value = MagicMock(returncode=0, stdout="apiVersion: v1\nkind: ConfigMap", stderr="")
        mock_kubectl.return_value = MagicMock(returncode=0, stdout="restarted", stderr="")
        scenario = ConfigBreakScenario()
        obs = scenario.execute("prod", {"action": "bad-config"})
        assert any("invalid" in o.lower() or "CrashLoopBackOff" in o for o in obs)

    @patch("src.chaos.scenarios._run_kubectl")
    def test_config_break_rollback(self, mock_kubectl):
        from src.chaos.scenarios import ConfigBreakScenario
        mock_kubectl.return_value = MagicMock(returncode=0, stdout="", stderr="")
        scenario = ConfigBreakScenario()
        obs = scenario.rollback("prod", {"deployment": "web", "good_image": "nginx:1.25"})
        assert any("Restored" in o for o in obs)

    @patch("src.chaos.scenarios._run_kubectl")
    def test_node_drain_execute_auto_select(self, mock_kubectl):
        from src.chaos.scenarios import NodeDrainScenario
        mock_kubectl.return_value = MagicMock(returncode=0, stdout="node-1", stderr="")
        scenario = NodeDrainScenario()
        obs = scenario.execute("default", {})
        assert any("Auto-selected" in o for o in obs)

    @patch("src.chaos.scenarios._run_kubectl")
    def test_node_drain_execute_specific_node(self, mock_kubectl):
        from src.chaos.scenarios import NodeDrainScenario
        mock_kubectl.return_value = MagicMock(returncode=0, stdout="drained", stderr="")
        scenario = NodeDrainScenario()
        obs = scenario.execute("default", {"node_name": "worker-1"})
        assert any("Cordoned" in o for o in obs)
        assert any("Drained" in o for o in obs)

    @patch("src.chaos.scenarios._run_kubectl")
    def test_node_drain_rollback_specific(self, mock_kubectl):
        from src.chaos.scenarios import NodeDrainScenario
        mock_kubectl.return_value = MagicMock(returncode=0, stdout="", stderr="")
        scenario = NodeDrainScenario()
        obs = scenario.rollback("default", {"node_name": "worker-1"})
        assert any("Uncordoned" in o for o in obs)

    @patch("src.chaos.scenarios._run_kubectl")
    def test_node_drain_rollback_all_nodes(self, mock_kubectl):
        from src.chaos.scenarios import NodeDrainScenario
        mock_kubectl.return_value = MagicMock(
            returncode=0, stdout="node-1 node-2", stderr=""
        )
        scenario = NodeDrainScenario()
        obs = scenario.rollback("default", {})
        # Should uncordon multiple nodes
        assert len(obs) >= 1

    @patch("src.chaos.scenarios._run_kubectl")
    def test_node_drain_rollback_all_nodes_error(self, mock_kubectl):
        from src.chaos.scenarios import NodeDrainScenario
        mock_kubectl.side_effect = Exception("kubectl unavailable")
        scenario = NodeDrainScenario()
        obs = scenario.rollback("default", {})
        assert any("Failed" in o for o in obs)


# ---------------------------------------------------------------------------
# 3. issues/manager — list_issues, get_issue, severity escalation
# ---------------------------------------------------------------------------
class TestIssueManagerExtended:
    """Cover gaps in IssueManager: list_issues filters, get_issue, severity escalation."""

    @pytest.fixture
    def manager(self):
        from src.issues.manager import IssueManager
        from src.issues.store import IssueStore
        return IssueManager(store=IssueStore())

    def test_list_issues_no_filter(self, manager):
        from src.issues.models import IssueType
        manager.create_issue(
            issue_type=IssueType.OOM_KILLED,
            title="OOM #1",
            namespace="default",
            resource="pod-1",
        )
        issues = manager.list_issues()
        assert len(issues) >= 1

    def test_list_issues_filter_by_status(self, manager):
        from src.issues.models import IssueType
        manager.create_issue(
            issue_type=IssueType.CRASH_LOOP,
            title="CrashLoop #1",
            namespace="kube-system",
            resource="pod-crash",
        )
        issues = manager.list_issues(status="detected")
        assert all(i.status.value == "detected" for i in issues)
        assert any(i.title == "CrashLoop #1" for i in issues)

    def test_list_issues_filter_by_severity(self, manager):
        from src.issues.models import IssueType
        manager.create_issue(
            issue_type=IssueType.CPU_THROTTLING,
            title="CPU throttle",
            namespace="default",
            resource="pod-cpu",
        )
        issues = manager.list_issues(severity="low")
        assert all(i.severity.value == "low" for i in issues)

    def test_list_issues_filter_by_namespace(self, manager):
        from src.issues.models import IssueType
        manager.create_issue(
            issue_type=IssueType.NETWORK_ERROR,
            title="Net error",
            namespace="production",
            resource="svc-api",
        )
        manager.create_issue(
            issue_type=IssueType.DISK_PRESSURE,
            title="Disk",
            namespace="staging",
            resource="node-1",
        )
        issues = manager.list_issues(namespace="production")
        assert all(i.namespace == "production" for i in issues)

    def test_get_issue_found(self, manager):
        from src.issues.models import IssueType
        created = manager.create_issue(
            issue_type=IssueType.OOM_KILLED,
            title="OOM",
            namespace="default",
            resource="p1",
        )
        fetched = manager.get_issue(created.id)
        assert fetched is not None
        assert fetched.id == created.id

    def test_get_issue_not_found(self, manager):
        result = manager.get_issue("nonexistent-id-12345")
        assert result is None

    def test_severity_escalation_high_restarts(self, manager):
        """Low severity escalated to medium when restarts > 10."""
        from src.issues.models import IssueType, IssueSeverity
        issue = manager.create_issue(
            issue_type=IssueType.CPU_THROTTLING,  # baseline LOW
            title="Throttle",
            namespace="default",
            resource="pod-x",
            metadata={"restarts": 15},
        )
        assert issue.severity == IssueSeverity.MEDIUM

    def test_severity_escalation_production(self, manager):
        """Low/medium severity escalated to high in production context."""
        from src.issues.models import IssueType, IssueSeverity
        issue = manager.create_issue(
            issue_type=IssueType.CPU_THROTTLING,  # baseline LOW
            title="Throttle in prod",
            namespace="production",
            resource="pod-y",
            metadata={"production": True},
        )
        assert issue.severity == IssueSeverity.HIGH

    def test_register_remediation_handler(self, manager):
        from src.issues.models import IssueType
        handler = MagicMock(return_value=True)
        manager.register_remediation_handler(IssueType.OOM_KILLED, handler)
        assert IssueType.OOM_KILLED in manager._remediation_handlers

    def test_update_status_not_found(self, manager):
        from src.issues.models import IssueStatus
        result = manager.update_status("ghost-id", IssueStatus.FIXED)
        assert result is None

    def test_add_root_cause_not_found(self, manager):
        result = manager.add_root_cause("ghost-id", "memory leak")
        assert result is None

    def test_record_fix_attempt_not_found(self, manager):
        result = manager.record_fix_attempt("ghost-id", "restart", "n/a", True)
        assert result is None

    def test_approve_fix_not_found(self, manager):
        result = manager.approve_fix("ghost-id")
        assert result is None
