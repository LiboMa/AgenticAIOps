"""Chaos Engine — orchestrates chaos experiment lifecycle with safety guards.

Provides create/run/rollback/list/get operations on chaos experiments,
with dry-run mode, namespace allowlists, concurrency limits, and
auto-rollback timeout enforcement.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .models import ChaosExperiment, ChaosResult, ChaosStatus, ChaosType
from .scenarios import SCENARIO_REGISTRY, BaseScenario

logger = logging.getLogger(__name__)


class ChaosEngineError(Exception):
    """Base exception for chaos engine errors."""


class NamespaceNotAllowed(ChaosEngineError):
    """Raised when target namespace is not in the allowlist."""


class ExperimentNotFound(ChaosEngineError):
    """Raised when experiment ID is not found."""


class MaxConcurrentExceeded(ChaosEngineError):
    """Raised when too many experiments are running concurrently."""


class ChaosEngine:
    """Orchestrates chaos experiment lifecycle with safety guards.

    Args:
        dry_run: If True, log kubectl commands but do not execute them.
        namespace_allowlist: Only these namespaces may be targeted.
        max_concurrent: Maximum number of simultaneously running experiments.
        auto_rollback_seconds: Auto-rollback after this many seconds (0 to disable).
    """

    def __init__(
        self,
        dry_run: bool = True,
        namespace_allowlist: Optional[List[str]] = None,
        max_concurrent: int = 3,
        auto_rollback_seconds: int = 600,
    ) -> None:
        self.dry_run = dry_run
        self.namespace_allowlist = namespace_allowlist or ["chaos-lab"]
        self.max_concurrent = max_concurrent
        self.auto_rollback_seconds = auto_rollback_seconds

        self._experiments: Dict[str, ChaosExperiment] = {}
        self._results: Dict[str, ChaosResult] = {}
        self._lock = threading.Lock()
        self._rollback_timers: Dict[str, threading.Timer] = {}

    # ── Experiment CRUD ──────────────────────────────────────────────

    def create_experiment(
        self,
        chaos_type: ChaosType,
        namespace: str = "chaos-lab",
        params: Optional[Dict[str, Any]] = None,
        name: Optional[str] = None,
        duration_seconds: int = 300,
    ) -> ChaosExperiment:
        """Create a new chaos experiment (does not execute it)."""
        # Validate namespace
        if namespace not in self.namespace_allowlist:
            raise NamespaceNotAllowed(
                f"Namespace '{namespace}' not in allowlist {self.namespace_allowlist}"
            )

        experiment = ChaosExperiment(
            name=name or f"{chaos_type.value}-{int(time.time())}",
            type=chaos_type,
            target_namespace=namespace,
            duration_seconds=duration_seconds,
            params=params or {},
        )

        with self._lock:
            self._experiments[experiment.id] = experiment

        logger.info("Created experiment %s (%s)", experiment.id, experiment.name)
        return experiment

    def get_experiment(self, experiment_id: str) -> ChaosExperiment:
        """Get an experiment by ID."""
        with self._lock:
            experiment = self._experiments.get(experiment_id)
        if not experiment:
            raise ExperimentNotFound(f"Experiment '{experiment_id}' not found")
        return experiment

    def list_experiments(self) -> List[ChaosExperiment]:
        """List all experiments."""
        with self._lock:
            return list(self._experiments.values())

    def delete_experiment(self, experiment_id: str) -> bool:
        """Delete an experiment. Cannot delete running experiments."""
        with self._lock:
            experiment = self._experiments.get(experiment_id)
            if not experiment:
                raise ExperimentNotFound(f"Experiment '{experiment_id}' not found")
            if experiment.status == ChaosStatus.RUNNING:
                raise ChaosEngineError("Cannot delete a running experiment. Rollback first.")
            del self._experiments[experiment_id]
            self._results.pop(experiment_id, None)
        logger.info("Deleted experiment %s", experiment_id)
        return True

    # ── Execution ────────────────────────────────────────────────────

    def _get_running_count(self) -> int:
        """Count currently running experiments (caller must hold _lock)."""
        return sum(
            1 for e in self._experiments.values()
            if e.status == ChaosStatus.RUNNING
        )

    def run_experiment(self, experiment_id: str) -> ChaosResult:
        """Execute a chaos experiment."""
        with self._lock:
            experiment = self._experiments.get(experiment_id)
            if not experiment:
                raise ExperimentNotFound(f"Experiment '{experiment_id}' not found")

            if experiment.status != ChaosStatus.PENDING:
                raise ChaosEngineError(
                    f"Experiment is '{experiment.status.value}', expected 'pending'"
                )

            running_count = self._get_running_count()
            if running_count >= self.max_concurrent:
                raise MaxConcurrentExceeded(
                    f"Max concurrent experiments ({self.max_concurrent}) reached"
                )

            experiment.status = ChaosStatus.RUNNING

        start_time = datetime.now(timezone.utc)
        observations: List[str] = []
        result_status = ChaosStatus.COMPLETED

        scenario = self._get_scenario(experiment.type)

        try:
            if self.dry_run:
                observations.append(
                    f"[DRY RUN] Would execute {experiment.type.value} "
                    f"in namespace {experiment.target_namespace}"
                )
                observations.append(f"[DRY RUN] Params: {experiment.params}")
                logger.info("Dry run: %s in %s", experiment.type.value, experiment.target_namespace)
            else:
                obs = scenario.execute(experiment.target_namespace, experiment.params)
                observations.extend(obs)

            # Set up auto-rollback timer
            if self.auto_rollback_seconds > 0 and not self.dry_run:
                timer = threading.Timer(
                    self.auto_rollback_seconds,
                    self._auto_rollback,
                    args=(experiment_id,),
                )
                timer.daemon = True
                timer.start()
                with self._lock:
                    self._rollback_timers[experiment_id] = timer
                observations.append(
                    f"Auto-rollback scheduled in {self.auto_rollback_seconds}s"
                )

        except Exception as e:
            logger.exception("Experiment %s failed", experiment_id)
            observations.append(f"Error: {e}")
            result_status = ChaosStatus.FAILED

            # Attempt rollback on failure
            try:
                if not self.dry_run:
                    rollback_obs = scenario.rollback(
                        experiment.target_namespace, experiment.params
                    )
                    observations.extend(rollback_obs)
                    observations.append("Auto-rollback on failure completed")
            except Exception as re:
                observations.append(f"Rollback also failed: {re}")

        end_time = datetime.now(timezone.utc)

        with self._lock:
            experiment.status = result_status

        result = ChaosResult(
            experiment_id=experiment_id,
            status=result_status,
            start_time=start_time,
            end_time=end_time,
            observations=observations,
            rollback_performed=(result_status == ChaosStatus.FAILED),
        )

        with self._lock:
            self._results[experiment_id] = result

        logger.info(
            "Experiment %s finished: %s (%d observations)",
            experiment_id, result_status.value, len(observations),
        )
        return result

    def rollback_experiment(self, experiment_id: str) -> bool:
        """Manually rollback an experiment."""
        with self._lock:
            experiment = self._experiments.get(experiment_id)
            if not experiment:
                raise ExperimentNotFound(f"Experiment '{experiment_id}' not found")

            # Cancel auto-rollback timer if present
            timer = self._rollback_timers.pop(experiment_id, None)
            if timer:
                timer.cancel()

        scenario = self._get_scenario(experiment.type)
        observations: List[str] = []

        try:
            if self.dry_run:
                observations.append(
                    f"[DRY RUN] Would rollback {experiment.type.value} "
                    f"in namespace {experiment.target_namespace}"
                )
            else:
                obs = scenario.rollback(experiment.target_namespace, experiment.params)
                observations.extend(obs)

            with self._lock:
                experiment.status = ChaosStatus.ROLLED_BACK
                existing_result = self._results.get(experiment_id)
                if existing_result:
                    existing_result.rollback_performed = True
                    existing_result.observations.extend(observations)
                    existing_result.end_time = datetime.now(timezone.utc)
                    existing_result.status = ChaosStatus.ROLLED_BACK

            logger.info("Experiment %s rolled back", experiment_id)
            return True

        except Exception as e:
            logger.exception("Rollback failed for %s", experiment_id)
            with self._lock:
                experiment.status = ChaosStatus.FAILED
            return False

    def get_result(self, experiment_id: str) -> Optional[ChaosResult]:
        """Get the result of an experiment, if available."""
        with self._lock:
            return self._results.get(experiment_id)

    # ── Internal helpers ─────────────────────────────────────────────

    def _get_scenario(self, chaos_type: ChaosType) -> BaseScenario:
        """Look up the scenario implementation for a chaos type."""
        scenario = SCENARIO_REGISTRY.get(chaos_type.value)
        if not scenario:
            raise ChaosEngineError(f"No scenario registered for type '{chaos_type.value}'")
        return scenario

    def _auto_rollback(self, experiment_id: str) -> None:
        """Auto-rollback callback triggered by timer."""
        logger.warning("Auto-rollback triggered for experiment %s", experiment_id)
        try:
            with self._lock:
                experiment = self._experiments.get(experiment_id)
                if not experiment or experiment.status != ChaosStatus.RUNNING:
                    return
            self.rollback_experiment(experiment_id)
        except Exception as e:
            logger.exception("Auto-rollback failed for %s: %s", experiment_id, e)
