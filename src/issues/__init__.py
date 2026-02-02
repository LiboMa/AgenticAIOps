"""
Issue Management System

Provides issue tracking, severity classification, and status management.
Foundation for the proactive AIOps agent.
"""

from .models import Issue, IssueSeverity, IssueStatus, IssueType
from .store import IssueStore
from .manager import IssueManager

__all__ = [
    "Issue",
    "IssueSeverity", 
    "IssueStatus",
    "IssueType",
    "IssueStore",
    "IssueManager",
]
