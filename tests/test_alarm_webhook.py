"""Tests for alarm_webhook — parse, extract, filter, handle."""

import os
import sys
import json
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.alarm_webhook import (
    parse_cloudwatch_alarm,
    extract_service_from_alarm,
    should_trigger_pipeline,
    handle_alarm_webhook,
)


class TestParseCloudwatchAlarm:

    def test_parse_json_message(self):
        sns = {
            "Message": json.dumps({
                "AlarmName": "HighCPU",
                "NewStateValue": "ALARM",
                "OldStateValue": "OK",
                "Trigger": {
                    "Namespace": "AWS/EC2",
                    "MetricName": "CPUUtilization",
                    "Threshold": 90,
                }
            })
        }
        result = parse_cloudwatch_alarm(sns)
        assert result["alarm_name"] == "HighCPU"
        assert result["new_state"] == "ALARM"
        assert result["namespace"] == "AWS/EC2"
        assert result["threshold"] == 90

    def test_parse_non_json_message(self):
        sns = {"Message": "plain text alert"}
        result = parse_cloudwatch_alarm(sns)
        assert result["alarm_name"] == "unknown"

    def test_parse_dict_message(self):
        data = {
            "AlarmName": "TestAlarm",
            "NewStateValue": "ALARM",
            "Trigger": {},
        }
        result = parse_cloudwatch_alarm(data)
        assert result["alarm_name"] == "TestAlarm"

    def test_missing_fields_defaults(self):
        result = parse_cloudwatch_alarm({})
        assert result["alarm_name"] == "unknown"
        assert result["new_state"] == ""
        assert result["namespace"] == ""


class TestExtractService:

    def test_ec2_namespace(self):
        assert extract_service_from_alarm({"namespace": "AWS/EC2"}) == "ec2"

    def test_rds_namespace(self):
        assert extract_service_from_alarm({"namespace": "AWS/RDS"}) == "rds"

    def test_lambda_namespace(self):
        assert extract_service_from_alarm({"namespace": "AWS/Lambda"}) == "lambda"

    def test_elb_namespace(self):
        assert extract_service_from_alarm({"namespace": "AWS/ApplicationELB"}) == "elb"

    def test_cwagent_maps_to_ec2(self):
        assert extract_service_from_alarm({"namespace": "CWAgent"}) == "ec2"

    def test_fallback_alarm_name(self):
        assert extract_service_from_alarm({"namespace": "", "alarm_name": "rds-cpu-high"}) == "rds"

    def test_unknown_returns_none(self):
        assert extract_service_from_alarm({"namespace": "Custom/Foo", "alarm_name": "xyz"}) is None


class TestShouldTrigger:

    def test_alarm_state_triggers(self):
        assert should_trigger_pipeline({"new_state": "ALARM", "old_state": "OK", "alarm_name": "t"}) is True

    def test_ok_state_skips(self):
        assert should_trigger_pipeline({"new_state": "OK", "alarm_name": "t"}) is False

    def test_insufficient_data_skips(self):
        assert should_trigger_pipeline({"new_state": "INSUFFICIENT_DATA", "alarm_name": "t"}) is False

    def test_alarm_to_alarm_skips(self):
        assert should_trigger_pipeline({"new_state": "ALARM", "old_state": "ALARM", "alarm_name": "t"}) is False


class TestHandleWebhook:

    @pytest.mark.asyncio
    async def test_sns_subscription_confirmation(self):
        with patch("urllib.request.urlopen"):
            result = await handle_alarm_webhook({
                "Type": "SubscriptionConfirmation",
                "SubscribeURL": "https://example.com/confirm",
            })
        assert result["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_sns_confirmation_failure(self):
        with patch("urllib.request.urlopen", side_effect=Exception("fail")):
            result = await handle_alarm_webhook({
                "Type": "SubscriptionConfirmation",
                "SubscribeURL": "https://bad-url",
            })
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_skip_non_alarm_state(self):
        result = await handle_alarm_webhook({
            "Message": json.dumps({
                "AlarmName": "Test",
                "NewStateValue": "OK",
            })
        })
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_trigger_full_pipeline(self):
        mock_incident = MagicMock()
        mock_incident.incident_id = "inc-123"
        mock_incident.status.value = "completed"
        mock_incident.duration_ms = 500
        mock_incident.rca_result = {"root_cause": "High CPU"}
        mock_incident.matched_sops = ["sop-1"]

        mock_orchestrator = MagicMock()
        mock_orchestrator.handle_incident = AsyncMock(return_value=mock_incident)

        with patch("src.incident_orchestrator.get_orchestrator", return_value=mock_orchestrator):
            result = await handle_alarm_webhook({
                "Message": json.dumps({
                    "AlarmName": "HighCPU",
                    "NewStateValue": "ALARM",
                    "OldStateValue": "OK",
                    "Trigger": {"Namespace": "AWS/EC2", "MetricName": "CPUUtilization"},
                })
            })

        assert result["status"] == "processed"
        assert result["incident_id"] == "inc-123"
        assert result["sop_matched"] == 1
