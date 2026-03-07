"""Batch tests for 5 skills tools modules — target >=75% coverage each."""
import json
import pytest
from unittest.mock import patch, MagicMock
from dataclasses import dataclass

# --------------- helpers ---------------

@dataclass
class FakeExecResult:
    stdout: str = ""
    stderr: str = ""
    return_code: int = 0
    duration_ms: int = 10
    timed_out: bool = False
    @property
    def ok(self):
        return self.return_code == 0 and not self.timed_out

def _ok(stdout="ok"):
    return FakeExecResult(stdout=stdout)

def _fail(stderr="err"):
    return FakeExecResult(stdout="", stderr=stderr, return_code=1)

def _parse(raw):
    return json.loads(raw)

# --------------- fixtures ---------------

@pytest.fixture(autouse=True)
def _set_tier():
    from src.skills._security import set_agent_context
    from src.skills._models import SecurityTier
    set_agent_context("test-agent", SecurityTier.T2_HIGH_RISK)
    yield

# ========== LOG ANALYSIS ==========
from src.skills.log_analysis import tools as log_tools

class TestCwLogsQuery:
    def test_success(self):
        with patch.object(log_tools, "_boto", return_value={"queryId": "q1"}):
            r = _parse(log_tools.cw_logs_query(log_group="/test"))
            assert r["status"] == "success"
            assert r["data"]["queryId"] == "q1"

class TestK8sPodLogs:
    def test_success(self):
        mock_kubectl = MagicMock()
        mock_kubectl.execute.return_value = _ok("log line 1")
        with patch.object(log_tools, "_kubectl", mock_kubectl):
            r = _parse(log_tools.k8s_pod_logs(pod_name="web-1"))
            assert r["status"] == "success"
            assert "log line 1" in r["data"]

    def test_with_container(self):
        mock_kubectl = MagicMock()
        mock_kubectl.execute.return_value = _ok("container log")
        with patch.object(log_tools, "_kubectl", mock_kubectl):
            r = _parse(log_tools.k8s_pod_logs(pod_name="web-1", container="nginx"))
            assert r["status"] == "success"
            mock_kubectl.execute.assert_called_once()
            args_call = mock_kubectl.execute.call_args
            assert "-c" in args_call[1].get("args", args_call[0][0]) or "-c" in str(args_call)

class TestLocalLogSearch:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("error found line")
        with patch.object(log_tools, "_shell", mock_shell):
            r = _parse(log_tools.local_log_search(log_path="/var/log/syslog", pattern="error"))
            assert r["status"] == "success"

class TestJournalctlQuery:
    def test_without_unit(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("journal output")
        with patch.object(log_tools, "_shell", mock_shell):
            r = _parse(log_tools.journalctl_query())
            assert r["status"] == "success"

    def test_with_unit(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("nginx journal")
        with patch.object(log_tools, "_shell", mock_shell):
            r = _parse(log_tools.journalctl_query(unit="nginx"))
            assert r["status"] == "success"
            cmd = mock_shell.execute.call_args[0][0]
            assert "-u nginx" in cmd

class TestCwLogGroups:
    def test_no_prefix(self):
        with patch.object(log_tools, "_boto", return_value={"logGroups": []}):
            r = _parse(log_tools.cw_log_groups())
            assert r["status"] == "success"

    def test_with_prefix(self):
        with patch.object(log_tools, "_boto", return_value={"logGroups": [{"name": "/aws/lambda"}]}):
            r = _parse(log_tools.cw_log_groups(prefix="/aws"))
            assert r["status"] == "success"

class TestErrorRateAnalysis:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.side_effect = [_ok("15"), _ok("1000")]
        with patch.object(log_tools, "_shell", mock_shell):
            r = _parse(log_tools.error_rate_analysis())
            assert r["status"] == "success"
            assert r["data"]["error_count"] == "15"
            assert r["data"]["total_lines"] == "1000"

class TestLogPatternDetect:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("  50 pattern A\n  30 pattern B")
        with patch.object(log_tools, "_shell", mock_shell):
            r = _parse(log_tools.log_pattern_detect())
            assert r["status"] == "success"

class TestMultiSourceSearch:
    def test_default_sources(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("match line")
        with patch.object(log_tools, "_shell", mock_shell):
            r = _parse(log_tools.multi_source_search(query="error"))
            assert r["status"] == "success"
            assert "syslog" in r["data"]
            assert "auth" in r["data"]

    def test_not_found(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = FakeExecResult(stderr="not found", return_code=1)
        with patch.object(log_tools, "_shell", mock_shell):
            r = _parse(log_tools.multi_source_search(query="xyz", sources="kern"))
            assert r["status"] == "success"

# ========== NETWORK ENGINEER ==========
from src.skills.network_engineer import tools as net_tools

class TestPingHost:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("64 bytes from 8.8.8.8")
        with patch.object(net_tools, "_shell", mock_shell):
            r = _parse(net_tools.ping_host(target="8.8.8.8"))
            assert r["status"] == "success"

class TestTraceroute:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("traceroute to 8.8.8.8")
        with patch.object(net_tools, "_shell", mock_shell):
            r = _parse(net_tools.traceroute(target="8.8.8.8"))
            assert r["status"] == "success"

class TestDnsLookup:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.side_effect = [_ok("1.2.3.4"), _ok("full dig output")]
        with patch.object(net_tools, "_shell", mock_shell):
            r = _parse(net_tools.dns_lookup(domain="example.com"))
            assert r["status"] == "success"
            assert r["data"]["short"] == "1.2.3.4"

class TestPortScan:
    def test_open_port(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = FakeExecResult(stdout="succeeded", return_code=0)
        with patch.object(net_tools, "_shell", mock_shell):
            r = _parse(net_tools.port_scan(target="localhost", ports="80"))
            assert r["status"] == "success"
            assert r["data"]["80"] == "open"

    def test_closed_port(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = FakeExecResult(stderr="refused", return_code=1)
        with patch.object(net_tools, "_shell", mock_shell):
            r = _parse(net_tools.port_scan(target="localhost", ports="9999"))
            assert r["status"] == "success"
            assert r["data"]["9999"] == "closed"

class TestNetworkInterfaces:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.side_effect = [_ok("eth0: ..."), _ok("default via ...")]
        with patch.object(net_tools, "_shell", mock_shell):
            r = _parse(net_tools.network_interfaces())
            assert r["status"] == "success"
            assert "interfaces" in r["data"]

class TestArpTable:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("192.168.1.1 dev eth0")
        with patch.object(net_tools, "_shell", mock_shell):
            r = _parse(net_tools.arp_table())
            assert r["status"] == "success"

class TestConnectionStats:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.side_effect = [_ok("TCP: 10"), _ok("LISTEN 0.0.0.0:80")]
        with patch.object(net_tools, "_shell", mock_shell):
            r = _parse(net_tools.connection_stats())
            assert r["status"] == "success"
            assert "summary" in r["data"]

class TestMtrReport:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("HOST: Loss%")
        with patch.object(net_tools, "_shell", mock_shell):
            r = _parse(net_tools.mtr_report(target="8.8.8.8"))
            assert r["status"] == "success"

class TestIptablesList:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("Chain INPUT")
        with patch.object(net_tools, "_shell", mock_shell):
            r = _parse(net_tools.iptables_list())
            assert r["status"] == "success"

class TestBandwidthTest:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("eth0: 1000 2000")
        with patch.object(net_tools, "_shell", mock_shell):
            r = _parse(net_tools.bandwidth_test())
            assert r["status"] == "success"

class TestFlushDns:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("flushed")
        with patch.object(net_tools, "_shell", mock_shell):
            r = _parse(net_tools.flush_dns())
            assert r["status"] == "success"

class TestRestartNetworkService:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("")
        with patch.object(net_tools, "_shell", mock_shell):
            r = _parse(net_tools.restart_network_service(service="systemd-networkd"))
            assert r["status"] == "success"

class TestModifyIptables:
    def test_list_action(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("Chain INPUT")
        with patch.object(net_tools, "_shell", mock_shell):
            with patch("src.approval_token.verify", return_value=(True, "ok")):
                r = _parse(net_tools.modify_iptables(action="list", approval_token="t"))
                assert r["status"] == "success"
                assert r["data"]["action"] == "list"

class TestModifyRoute:
    def test_show_action(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("default via 10.0.0.1")
        with patch.object(net_tools, "_shell", mock_shell):
            with patch("src.approval_token.verify", return_value=(True, "ok")):
                r = _parse(net_tools.modify_route(action="show", approval_token="t"))
                assert r["status"] == "success"

# ========== LINUX ADMIN ==========
from src.skills.linux_admin import tools as la_tools

class TestProcessAnalysis:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.side_effect = [_ok("PID CPU"), _ok("0.50 0.40 0.30")]
        with patch.object(la_tools, "_shell", mock_shell):
            r = _parse(la_tools.process_analysis())
            assert r["status"] == "success"
            assert "processes" in r["data"]

class TestResourceStats:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.side_effect = [_ok("Mem: 8G"), _ok("/ 50G"), _ok("0.5")]
        with patch.object(la_tools, "_shell", mock_shell):
            r = _parse(la_tools.resource_stats())
            assert r["status"] == "success"

class TestDiskAnalysis:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.side_effect = [_ok("/ 50G 30G"), _ok("10G /var")]
        with patch.object(la_tools, "_shell", mock_shell):
            r = _parse(la_tools.disk_analysis())
            assert r["status"] == "success"

class TestIoStats:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("sda 100 200")
        with patch.object(la_tools, "_shell", mock_shell):
            r = _parse(la_tools.io_stats())
            assert r["status"] == "success"

class TestNetworkDiagnose:
    def test_ss(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("LISTEN *:80")
        with patch.object(la_tools, "_shell", mock_shell):
            r = _parse(la_tools.network_diagnose(tool="ss"))
            assert r["status"] == "success"

class TestFileSearch:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("/var/log/syslog")
        with patch.object(la_tools, "_shell", mock_shell):
            r = _parse(la_tools.file_search(pattern="error"))
            assert r["status"] == "success"

class TestLogTail:
    def test_no_pattern(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("log line")
        with patch.object(la_tools, "_shell", mock_shell):
            r = _parse(la_tools.log_tail())
            assert r["status"] == "success"

    def test_with_pattern(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("error line")
        with patch.object(la_tools, "_shell", mock_shell):
            r = _parse(la_tools.log_tail(pattern="error"))
            assert r["status"] == "success"
            cmd = mock_shell.execute.call_args[0][0]
            assert "grep" in cmd

class TestSystemdStatus:
    def test_no_service(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("0 loaded units listed")
        with patch.object(la_tools, "_shell", mock_shell):
            r = _parse(la_tools.systemd_status())
            assert r["status"] == "success"

    def test_with_service(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("nginx.service - active")
        with patch.object(la_tools, "_shell", mock_shell):
            r = _parse(la_tools.systemd_status(service="nginx"))
            assert r["status"] == "success"

class TestOpenFiles:
    def test_port_mode(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("nginx 1234 TCP *:80")
        with patch.object(la_tools, "_shell", mock_shell):
            r = _parse(la_tools.open_files(target="80", mode="port"))
            assert r["status"] == "success"

    def test_no_target(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("LISTEN 0.0.0.0:22")
        with patch.object(la_tools, "_shell", mock_shell):
            r = _parse(la_tools.open_files())
            assert r["status"] == "success"

class TestKernelInfo:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.side_effect = [_ok("Linux 5.15"), _ok("warn: something")]
        with patch.object(la_tools, "_shell", mock_shell):
            r = _parse(la_tools.kernel_info())
            assert r["status"] == "success"
            assert "uname" in r["data"]

class TestUserSessions:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("user pts/0")
        with patch.object(la_tools, "_shell", mock_shell):
            r = _parse(la_tools.user_sessions())
            assert r["status"] == "success"

class TestCronList:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.side_effect = [_ok("*/5 * * * * backup"), _ok("daily.timer")]
        with patch.object(la_tools, "_shell", mock_shell):
            r = _parse(la_tools.cron_list())
            assert r["status"] == "success"
            assert "crontab" in r["data"]

class TestServiceRestart:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.side_effect = [_ok(""), _ok("active (running)")]
        with patch.object(la_tools, "_shell", mock_shell):
            r = _parse(la_tools.service_restart(service="nginx"))
            assert r["status"] == "success"

class TestProcessSignal:
    def test_allowed_signal(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("")
        with patch.object(la_tools, "_shell", mock_shell):
            r = _parse(la_tools.process_signal(pid=1234, signal="TERM"))
            assert r["status"] == "success"

    def test_blocked_signal(self):
        mock_shell = MagicMock()
        with patch.object(la_tools, "_shell", mock_shell):
            r = _parse(la_tools.process_signal(pid=1234, signal="KILL"))
            assert r["status"] == "blocked"

class TestFileEdit:
    def test_append(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("")
        with patch.object(la_tools, "_shell", mock_shell):
            r = _parse(la_tools.file_edit(path="/tmp/test.conf", content="line1", append=True))
            assert r["status"] == "success"
            assert r["data"]["append"] is True

class TestPackageQuery:
    def test_with_package(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("Package: nginx\nStatus: installed")
        with patch.object(la_tools, "_shell", mock_shell):
            r = _parse(la_tools.package_query(package="nginx"))
            assert r["status"] == "success"

    def test_no_package(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("ii  nginx  1.18")
        with patch.object(la_tools, "_shell", mock_shell):
            r = _parse(la_tools.package_query())
            assert r["status"] == "success"

class TestProcessKill:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.return_value = _ok("")
        with patch.object(la_tools, "_shell", mock_shell):
            with patch("src.approval_token.verify", return_value=(True, "ok")):
                r = _parse(la_tools.process_kill(pid=9999, approval_token="t"))
                assert r["status"] == "success"

class TestSystemReboot:
    def test_success(self):
        from src.skills._security import set_agent_context
        from src.skills._models import SecurityTier
        set_agent_context("test-agent", SecurityTier.T3_DESTRUCTIVE)
        try:
            with patch("src.approval_token.verify", return_value=(True, "ok")):
                r = _parse(la_tools.system_reboot(approval_token="t1", approval_token_2="t2"))
                assert r["status"] == "success"
                assert r["data"]["action"] == "reboot"
        finally:
            set_agent_context("test-agent", SecurityTier.T2_HIGH_RISK)

# ========== DATABASE ADMIN ==========
from src.skills.database_admin import tools as db_tools

class TestRdsInstanceStatus:
    def test_success(self):
        with patch.object(db_tools, "_boto", return_value={"DBInstances": []}):
            r = _parse(db_tools.rds_instance_status())
            assert r["status"] == "success"

class TestRdsClusterStatus:
    def test_success(self):
        with patch.object(db_tools, "_boto", return_value={"DBClusters": []}):
            r = _parse(db_tools.rds_cluster_status())
            assert r["status"] == "success"

class TestRdsEvents:
    def test_success(self):
        with patch.object(db_tools, "_boto", return_value={"Events": []}):
            r = _parse(db_tools.rds_events())
            assert r["status"] == "success"

class TestDynamodbListTables:
    def test_success(self):
        with patch.object(db_tools, "_boto", return_value={"TableNames": ["t1"]}):
            r = _parse(db_tools.dynamodb_list_tables())
            assert r["status"] == "success"

class TestDynamodbDescribeTable:
    def test_success(self):
        with patch.object(db_tools, "_boto", return_value={"Table": {"TableName": "t1"}}):
            r = _parse(db_tools.dynamodb_describe_table(table_name="t1"))
            assert r["status"] == "success"

class TestElasticacheStatus:
    def test_success(self):
        with patch.object(db_tools, "_boto", return_value={"CacheClusters": []}):
            r = _parse(db_tools.elasticache_status())
            assert r["status"] == "success"

class TestRdsSlowQueries:
    def test_success(self):
        with patch.object(db_tools, "_boto", return_value={"DescribeDBLogFiles": []}):
            r = _parse(db_tools.rds_slow_queries(db_instance_id="mydb"))
            assert r["status"] == "success"

class TestRdsPerformanceInsights:
    def test_success(self):
        r = _parse(db_tools.rds_performance_insights(db_instance_id="mydb"))
        assert r["status"] == "success"
        assert r["data"]["db_instance"] == "mydb"

class TestRdsCreateSnapshot:
    def test_success(self):
        with patch.object(db_tools, "_boto", return_value={"DBSnapshot": {"DBSnapshotIdentifier": "snap1"}}):
            r = _parse(db_tools.rds_create_snapshot(db_instance_id="mydb", snapshot_id="snap1"))
            assert r["status"] == "success"

class TestElasticacheRebootNode:
    def test_success(self):
        with patch.object(db_tools, "_boto", return_value={"CacheCluster": {}}):
            r = _parse(db_tools.elasticache_reboot_node(cluster_id="c1", node_id="0001"))
            assert r["status"] == "success"

class TestRdsFailoverCluster:
    def test_success(self):
        with patch.object(db_tools, "_boto", return_value={"DBCluster": {}}):
            with patch("src.approval_token.verify", return_value=(True, "ok")):
                r = _parse(db_tools.rds_failover_cluster(cluster_id="c1", approval_token="t"))
                assert r["status"] == "success"

class TestRdsModifyInstance:
    def test_success(self):
        with patch.object(db_tools, "_boto", return_value={"DBInstance": {}}):
            with patch("src.approval_token.verify", return_value=(True, "ok")):
                r = _parse(db_tools.rds_modify_instance(db_instance_id="mydb", instance_class="db.r5.large", approval_token="t"))
                assert r["status"] == "success"

    def test_no_class(self):
        with patch.object(db_tools, "_boto", return_value={"DBInstance": {}}):
            with patch("src.approval_token.verify", return_value=(True, "ok")):
                r = _parse(db_tools.rds_modify_instance(db_instance_id="mydb", approval_token="t"))
                assert r["status"] == "success"

# ========== STORAGE ==========
from src.skills.storage import tools as st_tools

class TestStorageListBuckets:
    def test_success(self):
        with patch.object(st_tools, "_boto", return_value={"Buckets": []}):
            r = _parse(st_tools.storage_list_buckets())
            assert r["status"] == "success"

class TestS3ListObjects:
    def test_success(self):
        with patch.object(st_tools, "_boto", return_value={"Contents": []}):
            r = _parse(st_tools.s3_list_objects(bucket="mybucket"))
            assert r["status"] == "success"

class TestEbsDescribeVolumes:
    def test_success(self):
        with patch.object(st_tools, "_boto", return_value={"Volumes": []}):
            r = _parse(st_tools.ebs_describe_volumes())
            assert r["status"] == "success"

class TestEfsDescribeFilesystems:
    def test_success(self):
        with patch.object(st_tools, "_boto", return_value={"FileSystems": []}):
            r = _parse(st_tools.efs_describe_filesystems())
            assert r["status"] == "success"

class TestLocalDiskUsage:
    def test_success(self):
        mock_shell = MagicMock()
        mock_shell.execute.side_effect = [_ok("/ 50G 30G"), _ok("10G /var")]
        with patch.object(st_tools, "_shell", mock_shell):
            r = _parse(st_tools.local_disk_usage())
            assert r["status"] == "success"

class TestEbsSnapshotList:
    def test_no_volume(self):
        with patch.object(st_tools, "_boto", return_value={"Snapshots": []}):
            r = _parse(st_tools.ebs_snapshot_list())
            assert r["status"] == "success"

    def test_with_volume(self):
        with patch.object(st_tools, "_boto", return_value={"Snapshots": [{"SnapshotId": "snap-1"}]}):
            r = _parse(st_tools.ebs_snapshot_list(volume_id="vol-123"))
            assert r["status"] == "success"

class TestS3BucketPolicy:
    def test_success(self):
        with patch.object(st_tools, "_boto", return_value={"Policy": "{}"}):
            r = _parse(st_tools.s3_bucket_policy(bucket="mybucket"))
            assert r["status"] == "success"

class TestEbsCreateSnapshot:
    def test_success(self):
        with patch.object(st_tools, "_boto", return_value={"SnapshotId": "snap-new"}):
            r = _parse(st_tools.ebs_create_snapshot(volume_id="vol-123"))
            assert r["status"] == "success"

class TestEbsDeleteSnapshot:
    def test_success(self):
        with patch.object(st_tools, "_boto", return_value={}):
            with patch("src.approval_token.verify", return_value=(True, "ok")):
                r = _parse(st_tools.ebs_delete_snapshot(snapshot_id="snap-1", approval_token="t"))
                assert r["status"] == "success"

class TestS3DeleteObjects:
    def test_dry_run(self):
        with patch.object(st_tools, "_boto", return_value={"Contents": []}):
            with patch("src.approval_token.verify", return_value=(True, "ok")):
                r = _parse(st_tools.s3_delete_objects(bucket="b", prefix="p", dry_run=True, approval_token="t"))
                assert r["status"] == "dry_run"

    def test_execute(self):
        with patch("src.approval_token.verify", return_value=(True, "ok")):
            r = _parse(st_tools.s3_delete_objects(bucket="b", prefix="p", approval_token="t"))
            assert r["status"] == "success"
            assert r["data"]["action"] == "delete"
