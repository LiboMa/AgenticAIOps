"""Targeted tests for ChaosEngine — uncovered lines.

Covers:
- Auto-rollback timer setup (lines 171-180) — live engine + subprocess mock
- Execution failure with auto-rollback on failure (lines 195-196)
- Manual rollback_experiment success path (lines 233, 260-264)
- Manual rollback_experiment failure path (lines 277, 282-290)
- _auto_rollback callback (line 282-290)
"""

import os
import sys
import time
import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.chaos.engine import ChaosEngine, ChaosEngineError, ExperimentNotFound
from src.chaos.models import ChaosExperiment, ChaosResult, ChaosStatus, ChaosType


@pytest.fixture
def live_engine():
    """Non-dry-run engine with auto-rollback."""
    return ChaosEngine(
        dry_run=False,
        namespace_allowlist=["chaos-lab"],
        max_concurrent=3,
        auto_rollback_seconds=0,  # Disabled by default
    )


@pytest.fixture
def rollback_engine():
    """Non-dry-run engine with short auto-rollback."""
    return ChaosEngine(
        dry_run=False,
        namespace_allowlist=["chaos-lab"],
        max_concurrent=3,
        auto_rollback_seconds=1,
    )


class TestAutoRollbackTimer:
    def test_auto_rollback_timer_is_set(self, rollback_engine):
        """When auto_rollback_seconds > 0 and not dry_run, timer is created."""
        exp = rollback_engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="pod/test-pod deleted",
                stderr="",
            )
            result = rollback_engine.run_experiment(exp.id)

        assert result.status == ChaosStatus.COMPLETED
        assert any("Auto-rollback scheduled" in o for o in result.observations)

        # Clean up timer
        with rollback_engine._lock:
            timer = rollback_engine._rollback_timers.get(exp.id)
            if timer:
                timer.cancel()


class TestExecutionFailureRollback:
    def test_failure_triggers_auto_rollback(self, live_engine):
        """When execution fails, automatic rollback is attempted."""
        exp = live_engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("kubectl failed")
            # Rollback call succeeds
            return MagicMock(returncode=0, stdout="rolled back", stderr="")

        with patch("subprocess.run", side_effect=side_effect):
            result = live_engine.run_experiment(exp.id)

        assert result.status == ChaosStatus.FAILED
        assert any("Error:" in o for o in result.observations)
        assert any("rollback" in o.lower() for o in result.observations)

    def test_failure_rollback_also_fails(self, live_engine):
        """When both execution and rollback fail."""
        exp = live_engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")

        with patch("subprocess.run", side_effect=RuntimeError("total failure")):
            result = live_engine.run_experiment(exp.id)

        assert result.status == ChaosStatus.FAILED
        assert any("Rollback also failed" in o for o in result.observations)


class TestManualRollback:
    def test_manual_rollback_success(self, live_engine):
        """Manual rollback sets status to ROLLED_BACK."""
        exp = live_engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")

        # First run the experiment successfully
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="pod deleted", stderr=""
            )
            live_engine.run_experiment(exp.id)

        # Then manually rollback
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="deployment scaled up", stderr=""
            )
            success = live_engine.rollback_experiment(exp.id)

        assert success is True
        with live_engine._lock:
            assert live_engine._experiments[exp.id].status == ChaosStatus.ROLLED_BACK

    def test_manual_rollback_cancels_timer(self, rollback_engine):
        """Manual rollback cancels auto-rollback timer if present."""
        exp = rollback_engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="ok", stderr=""
            )
            rollback_engine.run_experiment(exp.id)

        # Verify timer was set
        with rollback_engine._lock:
            assert exp.id in rollback_engine._rollback_timers

        # Manual rollback should cancel it
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="rolled back", stderr=""
            )
            rollback_engine.rollback_experiment(exp.id)

        with rollback_engine._lock:
            assert exp.id not in rollback_engine._rollback_timers

    def test_manual_rollback_failure(self, live_engine):
        """Manual rollback failure sets status to FAILED."""
        exp = live_engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="ok", stderr=""
            )
            live_engine.run_experiment(exp.id)

        with patch("subprocess.run", side_effect=RuntimeError("rollback failed")):
            success = live_engine.rollback_experiment(exp.id)

        assert success is False
        with live_engine._lock:
            assert live_engine._experiments[exp.id].status == ChaosStatus.FAILED

    def test_rollback_not_found(self, live_engine):
        with pytest.raises(ExperimentNotFound):
            live_engine.rollback_experiment("nonexistent-id")

    def test_rollback_updates_existing_result(self, live_engine):
        """Manual rollback updates the existing ChaosResult."""
        exp = live_engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="pod deleted", stderr=""
            )
            live_engine.run_experiment(exp.id)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="rolled back ok", stderr=""
            )
            live_engine.rollback_experiment(exp.id)

        result = live_engine.get_result(exp.id)
        assert result is not None
        assert result.rollback_performed is True
        assert result.status == ChaosStatus.ROLLED_BACK


class TestAutoRollbackCallback:
    def test_auto_rollback_fires(self):
        """_auto_rollback triggers rollback for RUNNING experiments."""
        engine = ChaosEngine(
            dry_run=False,
            namespace_allowlist=["chaos-lab"],
            max_concurrent=3,
            auto_rollback_seconds=0,
        )
        exp = engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")

        # Set status to RUNNING manually
        with engine._lock:
            engine._experiments[exp.id].status = ChaosStatus.RUNNING

        with patch.object(engine, "rollback_experiment", return_value=True) as mock_rb:
            engine._auto_rollback(exp.id)
            mock_rb.assert_called_once_with(exp.id)

    def test_auto_rollback_skips_non_running(self):
        """_auto_rollback does nothing if experiment is not RUNNING."""
        engine = ChaosEngine(
            dry_run=False,
            namespace_allowlist=["chaos-lab"],
            max_concurrent=3,
            auto_rollback_seconds=0,
        )
        exp = engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")

        # Status is PENDING, not RUNNING
        with patch.object(engine, "rollback_experiment") as mock_rb:
            engine._auto_rollback(exp.id)
            mock_rb.assert_not_called()

    def test_auto_rollback_handles_exception(self):
        """_auto_rollback catches exceptions."""
        engine = ChaosEngine(
            dry_run=False,
            namespace_allowlist=["chaos-lab"],
            max_concurrent=3,
            auto_rollback_seconds=0,
        )
        exp = engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")

        with engine._lock:
            engine._experiments[exp.id].status = ChaosStatus.RUNNING

        with patch.object(engine, "rollback_experiment", side_effect=Exception("fail")):
            # Should not raise
            engine._auto_rollback(exp.id)
