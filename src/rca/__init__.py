"""
Root Cause Analysis (RCA) Module

Provides pattern-based root cause identification with automatic severity
classification and remediation recommendations.

Network context enrichment (via ACI Topology) adds infrastructure-level
evidence to supplement application-level diagnosis.
"""

from .models import Pattern, RCAResult, Severity, Remediation, Symptom
from .network_context import NetworkContext, NetworkContextEnricher
from .pattern_matcher import PatternMatcher
from .engine import RCAEngine

__all__ = [
    "Pattern",
    "RCAResult", 
    "Severity",
    "Remediation",
    "Symptom",
    "PatternMatcher",
    "RCAEngine",
    "NetworkContext",
    "NetworkContextEnricher",
]
