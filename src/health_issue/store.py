"""
HealthIssue Store — JSON file persistence (SQLAlchemy-ready interface)

Stores:
  data/health_issues.json
  data/fix_plans.json
  data/rca_results.json

The public API (create / get / update / list / delete + filters) is designed
so that swapping in SQLAlchemy later only requires changing the implementation
behind the same method signatures.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .models import FixPlan, HealthIssue, HealthIssueStatus, RCAResult

logger = logging.getLogger(__name__)

_DEFAULT_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")


class HealthIssueStore:
    """CRUD store backed by JSON files.

    Parameters
    ----------
    data_dir : str
        Path to the directory that holds the JSON files.
    """

    def __init__(self, data_dir: str = _DEFAULT_DATA_DIR) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)

        self._issues_file = self._data_dir / "health_issues.json"
        self._fix_plans_file = self._data_dir / "fix_plans.json"
        self._rca_results_file = self._data_dir / "rca_results.json"

    # -- low-level I/O --------------------------------------------------------

    def _read_json(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, IOError) as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            return []

    def _write_json(self, path: Path, data: List[Dict[str, Any]]) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)

    # -----------------------------------------------------------------------
    # HealthIssue CRUD
    # -----------------------------------------------------------------------

    def create_issue(self, issue: HealthIssue) -> HealthIssue:
        records = self._read_json(self._issues_file)
        records.append(issue.to_dict())
        self._write_json(self._issues_file, records)
        return issue

    def get_issue(self, issue_id: str) -> Optional[HealthIssue]:
        for rec in self._read_json(self._issues_file):
            if rec.get("id") == issue_id:
                return HealthIssue.from_dict(rec)
        return None

    def update_issue(self, issue: HealthIssue) -> HealthIssue:
        records = self._read_json(self._issues_file)
        for idx, rec in enumerate(records):
            if rec.get("id") == issue.id:
                records[idx] = issue.to_dict()
                self._write_json(self._issues_file, records)
                return issue
        raise KeyError(f"HealthIssue {issue.id} not found")

    def delete_issue(self, issue_id: str) -> bool:
        records = self._read_json(self._issues_file)
        new_records = [r for r in records if r.get("id") != issue_id]
        if len(new_records) == len(records):
            return False
        self._write_json(self._issues_file, new_records)
        return True

    def list_issues(
        self,
        *,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        resource_type: Optional[str] = None,
    ) -> List[HealthIssue]:
        """Return issues with optional filters."""
        records = self._read_json(self._issues_file)
        results: List[HealthIssue] = []
        for rec in records:
            if status and rec.get("status") != status:
                continue
            if severity and rec.get("severity") != severity:
                continue
            if resource_type and rec.get("resource_type") != resource_type:
                continue
            results.append(HealthIssue.from_dict(rec))
        return results

    # -----------------------------------------------------------------------
    # FixPlan CRUD
    # -----------------------------------------------------------------------

    def create_fix_plan(self, plan: FixPlan) -> FixPlan:
        records = self._read_json(self._fix_plans_file)
        records.append(plan.to_dict())
        self._write_json(self._fix_plans_file, records)
        return plan

    def get_fix_plan(self, plan_id: str) -> Optional[FixPlan]:
        for rec in self._read_json(self._fix_plans_file):
            if rec.get("id") == plan_id:
                return FixPlan.from_dict(rec)
        return None

    def update_fix_plan(self, plan: FixPlan) -> FixPlan:
        records = self._read_json(self._fix_plans_file)
        for idx, rec in enumerate(records):
            if rec.get("id") == plan.id:
                records[idx] = plan.to_dict()
                self._write_json(self._fix_plans_file, records)
                return plan
        raise KeyError(f"FixPlan {plan.id} not found")

    def list_fix_plans(self, *, health_issue_id: Optional[str] = None) -> List[FixPlan]:
        records = self._read_json(self._fix_plans_file)
        results: List[FixPlan] = []
        for rec in records:
            if health_issue_id and rec.get("health_issue_id") != health_issue_id:
                continue
            results.append(FixPlan.from_dict(rec))
        return results

    # -----------------------------------------------------------------------
    # RCAResult CRUD
    # -----------------------------------------------------------------------

    def create_rca_result(self, rca: RCAResult) -> RCAResult:
        records = self._read_json(self._rca_results_file)
        records.append(rca.to_dict())
        self._write_json(self._rca_results_file, records)
        return rca

    def get_rca_result(self, rca_id: str) -> Optional[RCAResult]:
        for rec in self._read_json(self._rca_results_file):
            if rec.get("id") == rca_id:
                return RCAResult.from_dict(rec)
        return None

    def list_rca_results(self, *, health_issue_id: Optional[str] = None) -> List[RCAResult]:
        records = self._read_json(self._rca_results_file)
        results: List[RCAResult] = []
        for rec in records:
            if health_issue_id and rec.get("health_issue_id") != health_issue_id:
                continue
            results.append(RCAResult.from_dict(rec))
        return results
