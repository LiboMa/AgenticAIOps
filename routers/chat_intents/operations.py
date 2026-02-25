"""Operations intents: EC2/RDS/Lambda ops, notifications, KB, RCA, SOP, incident, safety."""

import re
import traceback
from typing import Optional

from routers.deps import get_scanner, get_current_region, logger


def _get_ops():
    try:
        from src.aws_ops import get_aws_ops
        return get_aws_ops(get_current_region())
    except ImportError:
        return None


async def handle(message: str, message_lower: str) -> Optional[str]:
    """Route operation intents. Returns None if not matched."""

    # --- EC2 Start ---
    if any(kw in message_lower for kw in ['ec2 start', 'start ec2', 'start instance']):
        return _ec2_action(message, 'start')

    # --- EC2 Stop ---
    if any(kw in message_lower for kw in ['ec2 stop', 'stop ec2', 'stop instance']):
        return _ec2_action(message, 'stop')

    # --- EC2 Reboot ---
    if any(kw in message_lower for kw in ['ec2 reboot', 'reboot ec2', 'reboot instance']):
        return _ec2_action(message, 'reboot')

    # --- RDS Reboot ---
    if any(kw in message_lower for kw in ['rds reboot', 'reboot rds', 'restart rds']):
        return _rds_reboot(message, message_lower)

    # --- RDS Failover ---
    if any(kw in message_lower for kw in ['rds failover', 'failover rds']):
        return _rds_failover(message, message_lower)

    # --- Lambda Invoke ---
    if any(kw in message_lower for kw in ['lambda invoke', 'invoke lambda']):
        return _lambda_invoke(message)

    # --- Notification Status ---
    if any(kw in message_lower for kw in ['notification status']):
        return _notification_status()

    # --- Test Notification ---
    if any(kw in message_lower for kw in ['test notification']):
        return _test_notification()

    # --- Send Alert ---
    if any(kw in message_lower for kw in ['send alert']):
        return _send_alert(message)

    # --- KB Stats ---
    if any(kw in message_lower for kw in ['kb stats', 'knowledge stats']):
        return _kb_stats()

    # --- KB Semantic Search (before keyword search) ---
    if any(kw in message_lower for kw in ['kb semantic', 'semantic search']):
        return _kb_semantic(message)

    # --- KB Search (keyword) ---
    if any(kw in message_lower for kw in ['kb search', 'knowledge search']) and 'semantic' not in message_lower:
        return _kb_search(message)

    # --- KB Index ---
    if any(kw in message_lower for kw in ['kb index', 'kb init', 'create index']):
        return _kb_index()

    # --- Learn from incident ---
    if any(kw in message_lower for kw in ['learn incident', 'learn from']):
        return _learn_incident()

    # --- Feedback ---
    if any(kw in message_lower for kw in ['feedback']):
        return _feedback(message, message_lower)

    # --- Incident Run (closed loop) ---
    if any(kw in message_lower for kw in ['incident run', 'incident handle', 'closed loop']):
        return await _incident_run(message, message_lower)

    # --- Incident List ---
    if any(kw in message_lower for kw in ['incident list', 'incidents']):
        return _incident_list()

    # --- Incident Stats ---
    if any(kw in message_lower for kw in ['incident stats']):
        return _incident_stats()

    # --- RCA Deep ---
    if any(kw in message_lower for kw in ['rca deep', 'deep analyze']):
        return await _rca_deep(message, message_lower)

    # --- RCA Analyze ---
    if any(kw in message_lower for kw in ['rca analyze', 'rca 分析', 'diagnose', 'root cause']):
        return _rca_analyze(message)

    # --- RCA Autofix ---
    if any(kw in message_lower for kw in ['rca autofix', 'auto diagnose']):
        return _rca_autofix(message)

    # --- RCA Feedback ---
    if any(kw in message_lower for kw in ['rca feedback']):
        return _rca_feedback(message_lower)

    # --- RCA Stats ---
    if any(kw in message_lower for kw in ['rca stats', 'rca status']):
        return _rca_stats()

    # --- Safety Check / Dry Run ---
    if any(kw in message_lower for kw in ['safety check', 'sop check', 'dry run', 'dry-run']):
        return _safety_check(message)

    # --- Safety Stats ---
    if any(kw in message_lower for kw in ['safety stats', 'safety status']):
        return _safety_stats()

    # --- Approvals ---
    if any(kw in message_lower for kw in ['approvals', 'pending approvals']):
        return _pending_approvals()

    # --- Approve / Reject ---
    if any(kw in message_lower for kw in ['approve ', 'reject ']):
        return _approve_reject(message)

    # --- SOP List ---
    if any(kw in message_lower for kw in ['sop list', 'list sop']):
        return _sop_list()

    # --- SOP Show ---
    if any(kw in message_lower for kw in ['sop show', 'show sop']):
        return _sop_show(message_lower)

    # --- SOP Suggest ---
    if any(kw in message_lower for kw in ['sop suggest', 'suggest sop']):
        return _sop_suggest(message)

    # --- SOP Run ---
    if any(kw in message_lower for kw in ['sop run', 'run sop', 'execute sop']):
        return _sop_run(message_lower)

    return None
