"""
Shared dependencies, global state, and conditional imports used across routers.
"""

import os
import logging

logger = logging.getLogger("aiops")

# ---------------------------------------------------------------------------
# AWS Scanner
# ---------------------------------------------------------------------------
try:
    from src.aws_scanner import get_scanner, AWSCloudScanner
    AWS_SCANNER_AVAILABLE = True
except ImportError as e:
    AWS_SCANNER_AVAILABLE = False
    def get_scanner(region):
        return None

# Global state for scanner
_current_region = "ap-southeast-1"


def get_current_region() -> str:
    return _current_region


def set_current_region(region: str):
    global _current_region
    _current_region = region


# ---------------------------------------------------------------------------
# K8s tools
# ---------------------------------------------------------------------------
K8S_TOOLS_AVAILABLE = False

try:
    from src.kubectl_wrapper import (
        get_pods, get_deployments, get_nodes, get_events,
        get_pod_logs, describe_pod, get_cluster_info, get_cluster_health
    )
    K8S_TOOLS_AVAILABLE = True
except Exception:
    def get_pods(ns=None):
        return {"pods": []}

    def get_deployments(ns=None):
        return {"deployments": []}

    def get_nodes():
        return {"nodes": []}

    def get_events(ns=None):
        return {"events": []}

    def get_pod_logs(ns, name, lines=100):
        return {"logs": ""}

    def describe_pod(ns, name):
        return {}

    def get_cluster_health():
        return {"status": "unknown"}

    def get_cluster_info():
        return {"name": "testing-cluster", "version": "1.32", "status": "ACTIVE", "region": "ap-southeast-1"}


def get_hpa(ns=None):
    return {"hpas": []}


# ---------------------------------------------------------------------------
# Intent / Voting
# ---------------------------------------------------------------------------
from src.intent_classifier import analyze_query
from src.voting import extract_diagnosis, simple_vote

# ---------------------------------------------------------------------------
# Plugin system
# ---------------------------------------------------------------------------
from src.plugins import PluginRegistry, PluginConfig
from src.plugins.eks_plugin import EKSPlugin
from src.plugins.ec2_plugin import EC2Plugin
from src.plugins.lambda_plugin import LambdaPlugin
from src.plugins.hpc_plugin import HPCPlugin

# ---------------------------------------------------------------------------
# ACI
# ---------------------------------------------------------------------------
try:
    from src.aci import AgentCloudInterface
    ACI_AVAILABLE = True
except Exception:
    ACI_AVAILABLE = False

# ---------------------------------------------------------------------------
# Voting
# ---------------------------------------------------------------------------
try:
    from src.voting import MultiAgentVoting, TaskType
    VOTING_AVAILABLE = True
except Exception:
    VOTING_AVAILABLE = False

# ---------------------------------------------------------------------------
# Issue Manager
# ---------------------------------------------------------------------------
try:
    from src.issues import IssueManager
    ISSUES_AVAILABLE = True
    _issue_manager = None
except Exception:
    ISSUES_AVAILABLE = False
    _issue_manager = None


def get_issue_manager():
    global _issue_manager
    if not ISSUES_AVAILABLE:
        return None
    if _issue_manager is None:
        _issue_manager = IssueManager()
    return _issue_manager


# ---------------------------------------------------------------------------
# Runbook Executor
# ---------------------------------------------------------------------------
try:
    from src.runbook import RunbookExecutor, RunbookLoader
    RUNBOOK_AVAILABLE = True
    _runbook_executor = None
except Exception:
    RUNBOOK_AVAILABLE = False
    _runbook_executor = None


def get_runbook_executor():
    global _runbook_executor
    if not RUNBOOK_AVAILABLE:
        return None
    if _runbook_executor is None:
        _runbook_executor = RunbookExecutor()
    return _runbook_executor


# ---------------------------------------------------------------------------
# Health Checker
# ---------------------------------------------------------------------------
try:
    from src.health import HealthChecker, HealthCheckScheduler, HealthCheckConfig
    HEALTH_AVAILABLE = True
    _health_scheduler = None
except Exception:
    HEALTH_AVAILABLE = False
    _health_scheduler = None


def get_health_scheduler():
    global _health_scheduler
    if not HEALTH_AVAILABLE:
        return None
    if _health_scheduler is None:
        config = HealthCheckConfig(
            enabled=False,
            interval_seconds=60,
        )
        _health_scheduler = HealthCheckScheduler(config=config)
    return _health_scheduler


# ---------------------------------------------------------------------------
# RCA in-memory store (simple list)
# ---------------------------------------------------------------------------
rca_reports: list = []

# ---------------------------------------------------------------------------
# Monitored resources (in-memory)
# ---------------------------------------------------------------------------
_monitored_resources: list = []


def get_monitored_resources():
    return _monitored_resources


def set_monitored_resources(resources):
    global _monitored_resources
    _monitored_resources = resources
