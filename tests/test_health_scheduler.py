"""
Tests for src/health/scheduler.py — HealthCheckScheduler.

Covers: init defaults, start/stop lifecycle, run_now, callbacks,
history management, status reporting, config update, and error handling.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from src.health.models import (
    CheckItem,
    CheckStatus,
    CheckType,
    HealthCheckConfig,
    HealthCheckResult,
)
from src.health.scheduler import HealthCheckScheduler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_result(status: CheckStatus = CheckStatus.HEALTHY, items=None):
    """Helper to build a HealthCheckResult."""
    return HealthCheckResult(
        check_type=CheckType.FULL,
        status=status,
        items=items or [],
    )


@pytest.fixture
def mock_checker():
    checker = MagicMock()
    checker.run_full_check.return_value = _make_result()
    return checker


@pytest.fixture
def scheduler(mock_checker):
    return HealthCheckScheduler(checker=mock_checker)


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestInit:
    def test_defaults(self, scheduler):
        assert scheduler.is_running is False
        assert scheduler.last_result is None
        assert scheduler._results_history == []
        assert scheduler._max_history == 100

    def test_custom_config(self):
        cfg = HealthCheckConfig(interval_seconds=120, enabled=False)
        s = HealthCheckScheduler(config=cfg)
        assert s.config.interval_seconds == 120
        assert s.config.enabled is False


# ---------------------------------------------------------------------------
# Start / Stop lifecycle
# ---------------------------------------------------------------------------

class TestStartStop:
    def test_start_and_stop(self, scheduler):
        scheduler.start()
        assert scheduler.is_running is True
        scheduler.stop()
        assert scheduler.is_running is False

    def test_start_when_disabled(self, mock_checker):
        cfg = HealthCheckConfig(enabled=False)
        s = HealthCheckScheduler(config=cfg, checker=mock_checker)
        s.start()
        assert s.is_running is False  # should not start

    def test_double_start_is_safe(self, scheduler):
        scheduler.start()
        scheduler.start()  # should warn but not crash
        assert scheduler.is_running is True
        scheduler.stop()

    def test_stop_when_not_running(self, scheduler):
        scheduler.stop()  # no-op, should not raise


# ---------------------------------------------------------------------------
# run_now / _run_check
# ---------------------------------------------------------------------------

class TestRunNow:
    def test_returns_result(self, scheduler, mock_checker):
        result = scheduler.run_now()
        assert result.status == CheckStatus.HEALTHY
        mock_checker.run_full_check.assert_called_once()

    def test_stores_last_result(self, scheduler):
        scheduler.run_now()
        assert scheduler.last_result is not None
        assert scheduler.last_result.status == CheckStatus.HEALTHY

    def test_appends_to_history(self, scheduler):
        scheduler.run_now()
        scheduler.run_now()
        assert len(scheduler._results_history) == 2

    def test_passes_namespaces(self, mock_checker):
        cfg = HealthCheckConfig(namespaces=["kube-system"])
        s = HealthCheckScheduler(config=cfg, checker=mock_checker)
        s.run_now()
        mock_checker.run_full_check.assert_called_with(namespaces=["kube-system"])

    def test_empty_namespaces_passes_none(self, mock_checker):
        cfg = HealthCheckConfig(namespaces=[])
        s = HealthCheckScheduler(config=cfg, checker=mock_checker)
        s.run_now()
        mock_checker.run_full_check.assert_called_with(namespaces=None)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

class TestCallbacks:
    def test_on_check_complete_fires(self, scheduler):
        cb = MagicMock()
        scheduler.on_check_complete = cb
        scheduler.run_now()
        cb.assert_called_once()

    def test_on_status_change_fires(self, scheduler, mock_checker):
        # First run: healthy
        scheduler.run_now()

        # Second run: critical → should trigger status change
        mock_checker.run_full_check.return_value = _make_result(CheckStatus.CRITICAL)
        cb = MagicMock()
        scheduler.on_status_change = cb
        scheduler.run_now()
        cb.assert_called_once()

    def test_on_status_change_not_fired_when_same(self, scheduler):
        cb = MagicMock()
        scheduler.on_status_change = cb
        scheduler.run_now()
        scheduler.run_now()  # still healthy
        cb.assert_not_called()

    def test_on_critical_fires(self, scheduler, mock_checker):
        mock_checker.run_full_check.return_value = _make_result(CheckStatus.CRITICAL)
        cb = MagicMock()
        scheduler.on_critical = cb
        scheduler.run_now()
        cb.assert_called_once()

    def test_on_critical_not_fired_for_healthy(self, scheduler):
        cb = MagicMock()
        scheduler.on_critical = cb
        scheduler.run_now()
        cb.assert_not_called()


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

class TestHistory:
    def test_get_history_empty(self, scheduler):
        assert scheduler.get_history() == []

    def test_get_history_limit(self, scheduler):
        for _ in range(5):
            scheduler.run_now()
        assert len(scheduler.get_history(limit=3)) == 3

    def test_history_trimmed_at_max(self, scheduler):
        scheduler._max_history = 5
        for _ in range(8):
            scheduler.run_now()
        assert len(scheduler._results_history) == 5


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------

class TestGetStatus:
    def test_status_when_idle(self, scheduler):
        status = scheduler.get_status()
        assert status["running"] is False
        assert status["enabled"] is True
        assert status["last_check"] is None
        assert status["history_count"] == 0

    def test_status_after_run(self, scheduler):
        scheduler.run_now()
        status = scheduler.get_status()
        assert status["last_check"] is not None
        assert status["history_count"] == 1


# ---------------------------------------------------------------------------
# update_config
# ---------------------------------------------------------------------------

class TestUpdateConfig:
    def test_update_while_stopped(self, scheduler, mock_checker):
        new_cfg = HealthCheckConfig(interval_seconds=300)
        scheduler.update_config(new_cfg)
        assert scheduler.config.interval_seconds == 300
        assert mock_checker.config.interval_seconds == 300

    def test_update_restarts_if_running(self, scheduler):
        scheduler.start()
        assert scheduler.is_running
        new_cfg = HealthCheckConfig(interval_seconds=300)
        scheduler.update_config(new_cfg)
        assert scheduler.is_running  # should auto-restart
        assert scheduler.config.interval_seconds == 300
        scheduler.stop()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_checker_exception_returns_unknown(self, scheduler, mock_checker):
        mock_checker.run_full_check.side_effect = RuntimeError("boom")
        result = scheduler.run_now()
        assert result.status == CheckStatus.UNKNOWN
        assert result.items == []
