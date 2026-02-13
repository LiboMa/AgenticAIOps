"""
EventBridge Auto-Trigger — Enables L4 autonomous incident response

Receives CloudWatch Alarm state changes via SNS → API Gateway → this handler,
and automatically triggers the incident orchestrator pipeline.

Architecture:
  CloudWatch Alarm → SNS Topic → API Gateway → /api/webhook/alarm → IncidentOrchestrator
  
Setup (Terraform/CLI):
  1. SNS Topic: agentic-aiops-alarms
  2. SNS Subscription: HTTPS → https://<api>/api/webhook/alarm
  3. CloudWatch Alarm Action → SNS Topic
  4. EventBridge Rule (optional): for scheduled/complex triggers

This is the bridge from AWS-native alerting to our AI-powered response.
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def parse_cloudwatch_alarm(sns_message: Dict[str, Any]) -> Dict[str, Any]:
    """Parse a CloudWatch Alarm SNS notification into trigger data."""
    # SNS wraps the alarm message as a JSON string in 'Message'
    if isinstance(sns_message.get('Message'), str):
        try:
            alarm_data = json.loads(sns_message['Message'])
        except json.JSONDecodeError:
            alarm_data = {"raw": sns_message.get('Message', '')}
    else:
        alarm_data = sns_message
    
    # Extract key fields
    trigger = alarm_data.get('Trigger', {})
    
    return {
        "alarm_name": alarm_data.get('AlarmName', 'unknown'),
        "alarm_description": alarm_data.get('AlarmDescription', ''),
        "new_state": alarm_data.get('NewStateValue', ''),
        "old_state": alarm_data.get('OldStateValue', ''),
        "reason": alarm_data.get('NewStateReason', ''),
        "timestamp": alarm_data.get('StateChangeTime', datetime.utcnow().isoformat()),
        "region": alarm_data.get('Region', 'ap-southeast-1'),
        "account_id": alarm_data.get('AWSAccountId', ''),
        
        # Metric details
        "namespace": trigger.get('Namespace', ''),
        "metric_name": trigger.get('MetricName', ''),
        "dimensions": trigger.get('Dimensions', []),
        "threshold": trigger.get('Threshold', 0),
        "comparison": trigger.get('ComparisonOperator', ''),
        "evaluation_periods": trigger.get('EvaluationPeriods', 0),
        "period": trigger.get('Period', 0),
        
        # Raw for debugging
        "_raw": alarm_data,
    }


def extract_service_from_alarm(trigger_data: Dict[str, Any]) -> Optional[str]:
    """Determine which AWS service the alarm is about."""
    namespace = trigger_data.get('namespace', '').lower()
    alarm_name = trigger_data.get('alarm_name', '').lower()
    
    service_map = {
        'aws/ec2': 'ec2',
        'aws/rds': 'rds',
        'aws/lambda': 'lambda',
        'aws/dynamodb': 'dynamodb',
        'aws/elb': 'elb',
        'aws/applicationelb': 'elb',
        'aws/ecs': 'ecs',
        'aws/eks': 'eks',
        'aws/s3': 's3',
        'cwagent': 'ec2',  # CloudWatch Agent → usually EC2
    }
    
    for ns, svc in service_map.items():
        if ns in namespace:
            return svc
    
    # Fallback: check alarm name
    for svc in ['ec2', 'rds', 'lambda', 'dynamodb', 'elb', 'ecs', 'eks']:
        if svc in alarm_name:
            return svc
    
    return None


def should_trigger_pipeline(trigger_data: Dict[str, Any]) -> bool:
    """Decide if this alarm should trigger the full incident pipeline."""
    # Only trigger on ALARM state (not OK or INSUFFICIENT_DATA)
    if trigger_data.get('new_state') != 'ALARM':
        logger.info(f"Skipping alarm {trigger_data['alarm_name']}: state={trigger_data['new_state']}")
        return False
    
    # Skip if transitioning from ALARM → ALARM (already being handled)
    if trigger_data.get('old_state') == 'ALARM':
        logger.info(f"Skipping alarm {trigger_data['alarm_name']}: already in ALARM state")
        return False
    
    return True


async def handle_alarm_webhook(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle incoming CloudWatch Alarm webhook (via SNS).
    
    This is the main entry point for automated incident response.
    Called by the /api/webhook/alarm endpoint.
    """
    from src.incident_orchestrator import get_orchestrator
    
    # Handle SNS subscription confirmation
    if body.get('Type') == 'SubscriptionConfirmation':
        subscribe_url = body.get('SubscribeURL', '')
        logger.info(f"SNS subscription confirmation: {subscribe_url}")
        # Auto-confirm by fetching the URL
        try:
            import urllib.request
            urllib.request.urlopen(subscribe_url)
            return {"status": "confirmed", "message": "SNS subscription confirmed"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to confirm: {e}"}
    
    # Parse alarm data
    trigger_data = parse_cloudwatch_alarm(body)
    
    # Check if we should respond
    if not should_trigger_pipeline(trigger_data):
        return {
            "status": "skipped",
            "alarm": trigger_data['alarm_name'],
            "reason": f"State: {trigger_data['new_state']}",
        }
    
    # Determine service filter
    service = extract_service_from_alarm(trigger_data)
    services = [service] if service else None
    
    logger.info(
        f"Alarm triggered: {trigger_data['alarm_name']} "
        f"({trigger_data['metric_name']}) → service={service}"
    )
    
    # Run the incident pipeline
    region = trigger_data.get('region', 'ap-southeast-1')
    orchestrator = get_orchestrator(region)
    
    incident = await orchestrator.handle_incident(
        trigger_type="alarm",
        trigger_data=trigger_data,
        services=services,
        auto_execute=True,   # L4: auto-execute L0/L1
        dry_run=False,
        lookback_minutes=15,
    )
    
    return {
        "status": "processed",
        "incident_id": incident.incident_id,
        "alarm": trigger_data['alarm_name'],
        "pipeline_status": incident.status.value,
        "duration_ms": incident.duration_ms,
        "rca_root_cause": incident.rca_result.get('root_cause', '') if incident.rca_result else None,
        "sop_matched": len(incident.matched_sops) if incident.matched_sops else 0,
    }
