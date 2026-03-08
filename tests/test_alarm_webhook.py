"""
Tests for src/alarm_webhook.py — CloudWatch Alarm webhook handler

Coverage target: 80%+ (from 0%)
"""

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone


# ── Test parse_cloudwatch_alarm ──────────────────────────────────────

class TestParseCloudWatchAlarm:
    """Test SNS alarm message parsing."""

    def test_parse_full_alarm_message(self):
        from src.alarm_webhook import parse_cloudwatch_alarm

        sns_message = {
            "Message": json.dumps({
                "AlarmName": "ec2-high-cpu",
                "AlarmDescription": "CPU > 90%",
                "NewStateValue": "ALARM",
                "OldStateValue": "OK",
                "NewStateReason": "Threshold Crossed",
                "StateChangeTime": "2026-02-13T10:00:00Z",
                "Region": "ap-southeast-1",
                "AWSAccountId": "123456789012",
                "Trigger": {
                    "Namespace": "AWS/EC2",
                    "MetricName": "CPUUtilization",
                    "Dimensions": [{"name": "InstanceId", "value": "i-abc123"}],
                    "Threshold": 90.0,
                    "ComparisonOperator": "GreaterThanThreshold",
                    "EvaluationPeriods": 3,
                    "Period": 60,
                },
            })
        }

        result = parse_cloudwatch_alarm(sns_message)

        assert result["alarm_name"] == "ec2-high-cpu"
        assert result["alarm_description"] == "CPU > 90%"
        assert result["new_state"] == "ALARM"
        assert result["old_state"] == "OK"
        assert result["namespace"] == "AWS/EC2"
        assert result["metric_name"] == "CPUUtilization"
        assert result["threshold"] == 90.0
        assert result["region"] == "ap-southeast-1"
        assert result["account_id"] == "123456789012"
        assert result["evaluation_periods"] == 3
        assert result["period"] == 60
        assert len(result["dimensions"]) == 1
        assert "_raw" in result

    def test_parse_non_json_message(self):
        from src.alarm_webhook import parse_cloudwatch_alarm

        sns_message = {"Message": "just a plain text message"}
        result = parse_cloudwatch_alarm(sns_message)
        assert result["alarm_name"] == "unknown"
        assert result["_raw"]["raw"] == "just a plain text message"

    def test_parse_dict_message_no_string(self):
        from src.alarm_webhook import parse_cloudwatch_alarm

        # Message is already a dict (not wrapped in string)
        sns_message = {
            "AlarmName": "direct-alarm",
            "NewStateValue": "ALARM",
            "Trigger": {},
        }
        result = parse_cloudwatch_alarm(sns_message)
        assert result["alarm_name"] == "direct-alarm"

    def test_parse_minimal_message(self):
        from src.alarm_webhook import parse_cloudwatch_alarm

        sns_message = {"Message": json.dumps({})}
        result = parse_cloudwatch_alarm(sns_message)
        assert result["alarm_name"] == "unknown"
        assert result["new_state"] == ""
        assert result["namespace"] == ""
        assert result["metric_name"] == ""
        assert result["threshold"] == 0

    def test_parse_missing_trigger(self):
        from src.alarm_webhook import parse_cloudwatch_alarm

        sns_message = {
            "Message": json.dumps({
                "AlarmName": "no-trigger-alarm",
                "NewStateValue": "OK",
            })
        }
        result = parse_cloudwatch_alarm(sns_message)
        assert result["alarm_name"] == "no-trigger-alarm"
        assert result["namespace"] == ""


# ── Test extract_service_from_alarm ──────────────────────────────────

class TestExtractServiceFromAlarm:
    """Test service extraction from alarm data."""

    def test_ec2_namespace(self):
        from src.alarm_webhook import extract_service_from_alarm
        assert extract_service_from_alarm({"namespace": "AWS/EC2"}) == "ec2"

    def test_rds_namespace(self):
        from src.alarm_webhook import extract_service_from_alarm
        assert extract_service_from_alarm({"namespace": "AWS/RDS"}) == "rds"

    def test_lambda_namespace(self):
        from src.alarm_webhook import extract_service_from_alarm
        assert extract_service_from_alarm({"namespace": "AWS/Lambda"}) == "lambda"

    def test_elb_namespace(self):
        from src.alarm_webhook import extract_service_from_alarm
        assert extract_service_from_alarm({"namespace": "AWS/ELB"}) == "elb"

    def test_application_elb_namespace(self):
        from src.alarm_webhook import extract_service_from_alarm
        assert extract_service_from_alarm({"namespace": "AWS/ApplicationELB"}) == "elb"

    def test_cwagent_namespace_maps_to_ec2(self):
        from src.alarm_webhook import extract_service_from_alarm
        assert extract_service_from_alarm({"namespace": "CWAgent"}) == "ec2"

    def test_eks_namespace(self):
        from src.alarm_webhook import extract_service_from_alarm
        assert extract_service_from_alarm({"namespace": "AWS/EKS"}) == "eks"

    def test_dynamodb_namespace(self):
        from src.alarm_webhook import extract_service_from_alarm
        assert extract_service_from_alarm({"namespace": "AWS/DynamoDB"}) == "dynamodb"

    def test_s3_namespace(self):
        from src.alarm_webhook import extract_service_from_alarm
        assert extract_service_from_alarm({"namespace": "AWS/S3"}) == "s3"

    def test_ecs_namespace(self):
        from src.alarm_webhook import extract_service_from_alarm
        assert extract_service_from_alarm({"namespace": "AWS/ECS"}) == "ecs"

    def test_fallback_to_alarm_name(self):
        from src.alarm_webhook import extract_service_from_alarm
        result = extract_service_from_alarm({
            "namespace": "Custom/MyApp",
            "alarm_name": "my-ec2-cpu-alarm",
        })
        assert result == "ec2"

    def test_fallback_rds_in_alarm_name(self):
        from src.alarm_webhook import extract_service_from_alarm
        result = extract_service_from_alarm({
            "namespace": "",
            "alarm_name": "rds-connection-count",
        })
        assert result == "rds"

    def test_unknown_service(self):
        from src.alarm_webhook import extract_service_from_alarm
        result = extract_service_from_alarm({
            "namespace": "Custom/Unknown",
            "alarm_name": "my-custom-alarm",
        })
        assert result is None


# ── Test should_trigger_pipeline ─────────────────────────────────────

class TestShouldTriggerPipeline:
    """Test pipeline trigger decision logic."""

    def test_alarm_state_triggers(self):
        from src.alarm_webhook import should_trigger_pipeline
        assert should_trigger_pipeline({
            "alarm_name": "test",
            "new_state": "ALARM",
            "old_state": "OK",
        }) is True

    def test_ok_state_does_not_trigger(self):
        from src.alarm_webhook import should_trigger_pipeline
        assert should_trigger_pipeline({
            "alarm_name": "test",
            "new_state": "OK",
            "old_state": "ALARM",
        }) is False

    def test_insufficient_data_does_not_trigger(self):
        from src.alarm_webhook import should_trigger_pipeline
        assert should_trigger_pipeline({
            "alarm_name": "test",
            "new_state": "INSUFFICIENT_DATA",
        }) is False

    def test_alarm_to_alarm_does_not_trigger(self):
        from src.alarm_webhook import should_trigger_pipeline
        assert should_trigger_pipeline({
            "alarm_name": "test",
            "new_state": "ALARM",
            "old_state": "ALARM",
        }) is False

    def test_insufficient_to_alarm_triggers(self):
        from src.alarm_webhook import should_trigger_pipeline
        assert should_trigger_pipeline({
            "alarm_name": "test",
            "new_state": "ALARM",
            "old_state": "INSUFFICIENT_DATA",
        }) is True


# ── Test handle_alarm_webhook (async) ────────────────────────────────

class TestHandleAlarmWebhook:
    """Test the main webhook handler."""

    @pytest.mark.asyncio
    async def test_sns_subscription_confirmation(self):
        from src.alarm_webhook import handle_alarm_webhook

        with patch('urllib.request.urlopen') as mock_urlopen:
            result = await handle_alarm_webhook({
                "Type": "SubscriptionConfirmation",
                "SubscribeURL": "https://sns.example.com/confirm?token=abc",
            })

        assert result["status"] == "confirmed"
        mock_urlopen.assert_called_once()

    @pytest.mark.asyncio
    async def test_sns_subscription_confirmation_failure(self):
        from src.alarm_webhook import handle_alarm_webhook

        with patch('urllib.request.urlopen', side_effect=Exception("network error")):
            result = await handle_alarm_webhook({
                "Type": "SubscriptionConfirmation",
                "SubscribeURL": "https://sns.example.com/confirm?token=abc",
            })

        assert result["status"] == "error"
        assert "Failed to confirm" in result["message"]

    @pytest.mark.asyncio
    async def test_skips_non_alarm_state(self):
        from src.alarm_webhook import handle_alarm_webhook

        result = await handle_alarm_webhook({
            "Message": json.dumps({
                "AlarmName": "test-alarm",
                "NewStateValue": "OK",
                "OldStateValue": "ALARM",
                "Trigger": {},
            })
        })

        assert result["status"] == "skipped"
        assert result["alarm"] == "test-alarm"

    @pytest.mark.asyncio
    async def test_triggers_pipeline_on_alarm(self):
        from src.alarm_webhook import handle_alarm_webhook

        mock_incident = MagicMock()
        mock_incident.incident_id = "inc-001"
        mock_incident.status.value = "completed"
        mock_incident.duration_ms = 1500
        mock_incident.rca_result = {"root_cause": "High CPU"}
        mock_incident.matched_sops = [{"id": "sop-1"}]

        mock_orchestrator = AsyncMock()
        mock_orchestrator.handle_incident.return_value = mock_incident

        with patch('src.incident_orchestrator.get_orchestrator', return_value=mock_orchestrator):
            result = await handle_alarm_webhook({
                "Message": json.dumps({
                    "AlarmName": "ec2-high-cpu",
                    "NewStateValue": "ALARM",
                    "OldStateValue": "OK",
                    "Region": "ap-southeast-1",
                    "Trigger": {
                        "Namespace": "AWS/EC2",
                        "MetricName": "CPUUtilization",
                    },
                })
            })

        assert result["status"] == "processed"
        assert result["incident_id"] == "inc-001"
        assert result["alarm"] == "ec2-high-cpu"
        assert result["sop_matched"] == 1
        mock_orchestrator.handle_incident.assert_called_once()
        call_kwargs = mock_orchestrator.handle_incident.call_args[1]
        assert call_kwargs["trigger_type"] == "alarm"
        assert call_kwargs["services"] == ["ec2"]
        assert call_kwargs["auto_execute"] is True

    @pytest.mark.asyncio
    async def test_pipeline_with_unknown_service(self):
        from src.alarm_webhook import handle_alarm_webhook

        mock_incident = MagicMock()
        mock_incident.incident_id = "inc-002"
        mock_incident.status.value = "completed"
        mock_incident.duration_ms = 500
        mock_incident.rca_result = None
        mock_incident.matched_sops = None

        mock_orchestrator = AsyncMock()
        mock_orchestrator.handle_incident.return_value = mock_incident

        with patch('src.incident_orchestrator.get_orchestrator', return_value=mock_orchestrator):
            result = await handle_alarm_webhook({
                "Message": json.dumps({
                    "AlarmName": "custom-alarm",
                    "NewStateValue": "ALARM",
                    "OldStateValue": "OK",
                    "Trigger": {"Namespace": "Custom/MyApp"},
                })
            })

        assert result["status"] == "processed"
        assert result["rca_root_cause"] is None
        assert result["sop_matched"] == 0
        call_kwargs = mock_orchestrator.handle_incident.call_args[1]
        assert call_kwargs["services"] is None  # unknown service
