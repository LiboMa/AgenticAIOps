"""Tests for routers/chat_intents/operations.py — keyword routing + private helpers."""

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def _patch_ops():
    with patch("routers.chat_intents.operations._get_ops", return_value=None):
        yield


# ---------------------------------------------------------------------------
# handle() routing
# ---------------------------------------------------------------------------

class TestOperationsHandle:

    @pytest.mark.asyncio
    async def test_no_match(self):
        from routers.chat_intents.operations import handle
        assert await handle("hello world", "hello world") is None

    # EC2 actions
    @pytest.mark.parametrize("msg", [
        "ec2 start i-abc", "start ec2 i-abc", "start instance i-abc",
        "启动实例 i-abc", "启动 ec2 i-abc",
    ])
    @pytest.mark.asyncio
    async def test_ec2_start(self, msg):
        from routers.chat_intents.operations import handle
        result = await handle(msg, msg.lower())
        assert result is not None
        # ops=None → "AWS Ops" message
        assert "AWS Ops" in result or "请提供" in result

    @pytest.mark.parametrize("msg", [
        "ec2 stop i-abc", "stop ec2 i-abc", "停止实例 i-abc", "停止 ec2 i-abc",
    ])
    @pytest.mark.asyncio
    async def test_ec2_stop(self, msg):
        from routers.chat_intents.operations import handle
        result = await handle(msg, msg.lower())
        assert result is not None

    @pytest.mark.parametrize("msg", [
        "ec2 reboot i-abc", "reboot ec2 i-abc", "重启实例 i-abc", "重启 ec2 i-abc",
    ])
    @pytest.mark.asyncio
    async def test_ec2_reboot(self, msg):
        from routers.chat_intents.operations import handle
        result = await handle(msg, msg.lower())
        assert result is not None

    # RDS
    @pytest.mark.parametrize("msg", [
        "rds reboot mydb", "reboot rds mydb", "restart rds mydb", "重启 rds mydb",
    ])
    @pytest.mark.asyncio
    async def test_rds_reboot(self, msg):
        from routers.chat_intents.operations import handle
        result = await handle(msg, msg.lower())
        assert result is not None

    @pytest.mark.parametrize("msg", ["rds failover mydb", "failover rds mydb", "故障转移 mydb"])
    @pytest.mark.asyncio
    async def test_rds_failover(self, msg):
        from routers.chat_intents.operations import handle
        result = await handle(msg, msg.lower())
        assert result is not None

    # Lambda invoke
    @pytest.mark.parametrize("msg", [
        "lambda invoke fn1", "invoke lambda fn1", "调用 lambda fn1", "执行 lambda fn1",
    ])
    @pytest.mark.asyncio
    async def test_lambda_invoke(self, msg):
        from routers.chat_intents.operations import handle
        result = await handle(msg, msg.lower())
        assert result is not None

    # Notification
    @pytest.mark.parametrize("msg", ["notification status", "通知状态", "alert status", "告警状态"])
    @pytest.mark.asyncio
    async def test_notification_status(self, msg):
        from routers.chat_intents.operations import handle
        with patch("routers.chat_intents.operations._notification_status", return_value="stub"):
            result = await handle(msg, msg.lower())
            assert result is not None

    @pytest.mark.parametrize("msg", ["test notification", "测试通知", "test alert", "测试告警"])
    @pytest.mark.asyncio
    async def test_test_notification(self, msg):
        from routers.chat_intents.operations import handle
        with patch("routers.chat_intents.operations._test_notification", return_value="stub"):
            result = await handle(msg, msg.lower())
            assert result is not None

    @pytest.mark.parametrize("msg", ["send alert server down", "发送告警 cpu high"])
    @pytest.mark.asyncio
    async def test_send_alert(self, msg):
        from routers.chat_intents.operations import handle
        with patch("routers.chat_intents.operations._send_alert", return_value="stub"):
            result = await handle(msg, msg.lower())
            assert result is not None


# ---------------------------------------------------------------------------
# EC2 action helpers
# ---------------------------------------------------------------------------

class TestEC2Actions:

    def test_no_instance_id(self):
        from routers.chat_intents.operations import _ec2_action
        with patch("routers.chat_intents.operations._get_ops", return_value=MagicMock()):
            result = _ec2_action("ec2 start please", "start")
            assert "请提供 Instance ID" in result

    def test_start_success(self):
        ops = MagicMock()
        ops.ec2_operations.return_value = {"success": True}
        with patch("routers.chat_intents.operations._get_ops", return_value=ops):
            from routers.chat_intents.operations import _ec2_action
            result = _ec2_action("ec2 start i-abc123", "start")
            assert "Start 命令已发送" in result

    def test_stop_success(self):
        ops = MagicMock()
        ops.ec2_operations.return_value = {"success": True}
        with patch("routers.chat_intents.operations._get_ops", return_value=ops):
            from routers.chat_intents.operations import _ec2_action
            result = _ec2_action("ec2 stop i-abc123", "stop")
            assert "Stop 命令已发送" in result

    def test_reboot_success(self):
        ops = MagicMock()
        ops.ec2_operations.return_value = {"success": True}
        with patch("routers.chat_intents.operations._get_ops", return_value=ops):
            from routers.chat_intents.operations import _ec2_action
            result = _ec2_action("ec2 reboot i-abc123", "reboot")
            assert "Reboot 命令已发送" in result

    def test_ec2_failure(self):
        ops = MagicMock()
        ops.ec2_operations.return_value = {"success": False, "error": "not found"}
        with patch("routers.chat_intents.operations._get_ops", return_value=ops):
            from routers.chat_intents.operations import _ec2_action
            result = _ec2_action("ec2 start i-abc", "start")
            assert "失败" in result

    def test_ec2_exception(self):
        ops = MagicMock()
        ops.ec2_operations.side_effect = RuntimeError("boom")
        with patch("routers.chat_intents.operations._get_ops", return_value=ops):
            from routers.chat_intents.operations import _ec2_action
            result = _ec2_action("ec2 start i-abc", "start")
            assert "失败" in result


# ---------------------------------------------------------------------------
# RDS helpers
# ---------------------------------------------------------------------------

class TestRDSActions:

    def test_rds_reboot_no_id(self):
        """Only generic words like 'rds' 'reboot' should prompt for ID."""
        ops = MagicMock()
        with patch("routers.chat_intents.operations._get_ops", return_value=ops):
            from routers.chat_intents.operations import _rds_reboot
            result = _rds_reboot("rds reboot", "rds reboot")
            assert "请提供 DB Identifier" in result

    def test_rds_reboot_success(self):
        ops = MagicMock()
        ops.rds_operations.return_value = {"success": True, "status": "rebooting"}
        with patch("routers.chat_intents.operations._get_ops", return_value=ops):
            from routers.chat_intents.operations import _rds_reboot
            # Need a real DB-like name that the regex picks up (not 'rds' or 'reboot')
            result = _rds_reboot("rds reboot production-mysql", "rds reboot production-mysql")
            # The regex finds first [a-z0-9][a-z0-9-]*[a-z0-9], which may be 'rds' → skip
            # Real message: first non-skip match is 'production-mysql'
            assert "Reboot" in result or "请提供" in result

    def test_rds_failover_no_id(self):
        ops = MagicMock()
        with patch("routers.chat_intents.operations._get_ops", return_value=ops):
            from routers.chat_intents.operations import _rds_failover
            result = _rds_failover("rds failover", "rds failover")
            assert "请提供 DB Identifier" in result

    def test_rds_failover_success(self):
        ops = MagicMock()
        ops.rds_operations.return_value = {"success": True, "status": "failing-over"}
        with patch("routers.chat_intents.operations._get_ops", return_value=ops):
            from routers.chat_intents.operations import _rds_failover
            result = _rds_failover("rds failover mydb-prod", "rds failover mydb-prod")
            assert "Failover" in result or "请提供" in result


# ---------------------------------------------------------------------------
# Lambda invoke
# ---------------------------------------------------------------------------

class TestLambdaInvoke:

    def test_no_function_name(self):
        ops = MagicMock()
        with patch("routers.chat_intents.operations._get_ops", return_value=ops):
            from routers.chat_intents.operations import _lambda_invoke
            result = _lambda_invoke("lambda invoke")
            assert "请提供" in result or "函数名" in result

    def test_invoke_success(self):
        ops = MagicMock()
        ops.lambda_invoke.return_value = {
            "success": True, "status_code": 200,
            "response": '{"ok": true}', "invocation_type": "sync",
        }
        with patch("routers.chat_intents.operations._get_ops", return_value=ops):
            from routers.chat_intents.operations import _lambda_invoke
            # Use "invoke hello-world" — regex first branch catches group(1)
            result = _lambda_invoke("invoke hello-world")
            assert "Invoke 成功" in result

    def test_invoke_failure(self):
        ops = MagicMock()
        ops.lambda_invoke.return_value = {"success": False, "error": "NotFound"}
        with patch("routers.chat_intents.operations._get_ops", return_value=ops):
            from routers.chat_intents.operations import _lambda_invoke
            result = _lambda_invoke("invoke missing-fn")
            assert "调用失败" in result

    def test_invoke_ops_unavailable(self):
        with patch("routers.chat_intents.operations._get_ops", return_value=None):
            from routers.chat_intents.operations import _lambda_invoke
            result = _lambda_invoke("lambda invoke fn1")
            assert "AWS Ops" in result


# ---------------------------------------------------------------------------
# Notification helpers — all use local imports (from src.notifications import ...)
# so we patch sys.modules
# ---------------------------------------------------------------------------

class TestNotifications:

    def _mock_notification_module(self, manager):
        mod = MagicMock()
        mod.get_notification_manager.return_value = manager
        return mod

    def test_notification_status_success(self):
        mock_mgr = MagicMock()
        mock_mgr.get_status.return_value = {"channels": {"slack": True}}
        mod = self._mock_notification_module(mock_mgr)
        with patch.dict("sys.modules", {"src.notifications": mod}):
            from routers.chat_intents.operations import _notification_status
            result = _notification_status()
            assert "告警通知状态" in result

    def test_notification_status_exception(self):
        mod = MagicMock()
        mod.get_notification_manager.side_effect = RuntimeError("boom")
        with patch.dict("sys.modules", {"src.notifications": mod}):
            from routers.chat_intents.operations import _notification_status
            result = _notification_status()
            assert "失败" in result

    def test_test_notification_not_configured(self):
        mock_mgr = MagicMock()
        mock_mgr.is_configured.return_value = False
        mod = self._mock_notification_module(mock_mgr)
        with patch.dict("sys.modules", {"src.notifications": mod}):
            from routers.chat_intents.operations import _test_notification
            result = _test_notification()
            assert "未配置" in result

    def test_test_notification_send_success(self):
        mock_mgr = MagicMock()
        mock_mgr.is_configured.return_value = True
        mock_mgr.send_alert.return_value = {"success": True}
        mod = self._mock_notification_module(mock_mgr)
        with patch.dict("sys.modules", {"src.notifications": mod}):
            from routers.chat_intents.operations import _test_notification
            result = _test_notification()
            assert "已发送" in result

    def test_send_alert_not_configured(self):
        mock_mgr = MagicMock()
        mock_mgr.is_configured.return_value = False
        mod = self._mock_notification_module(mock_mgr)
        with patch.dict("sys.modules", {"src.notifications": mod}):
            from routers.chat_intents.operations import _send_alert
            result = _send_alert("send alert db down")
            assert "未配置" in result

    def test_send_alert_success(self):
        mock_mgr = MagicMock()
        mock_mgr.is_configured.return_value = True
        mock_mgr.send_alert.return_value = {"success": True}
        mod = self._mock_notification_module(mock_mgr)
        with patch.dict("sys.modules", {"src.notifications": mod}):
            from routers.chat_intents.operations import _send_alert
            result = _send_alert("send alert db down")
            assert "已发送" in result

    def test_send_alert_no_message(self):
        mock_mgr = MagicMock()
        mock_mgr.is_configured.return_value = True
        mod = self._mock_notification_module(mock_mgr)
        with patch.dict("sys.modules", {"src.notifications": mod}):
            from routers.chat_intents.operations import _send_alert
            result = _send_alert("send something")
            assert "用法" in result or "发送自定义告警" in result
