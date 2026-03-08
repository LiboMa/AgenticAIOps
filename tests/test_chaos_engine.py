"""Tests for ChaosEngine — mock subprocess, no real kubectl calls."""

from __future__ import annotations

import subprocess
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.chaos.engine import (
    ChaosEngine,
    ChaosEngineError,
    ExperimentNotFound,
    MaxConcurrentExceeded,
    NamespaceNotAllowed,
)
from src.chaos.models import ChaosExperiment, ChaosResult, ChaosStatus, ChaosType


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def engine() -> ChaosEngine:
    """Create a dry-run ChaosEngine for testing."""
    return ChaosEngine(
        dry_run=True,
        namespace_allowlist=["chaos-lab", "test-ns"],
        max_concurrent=2,
        auto_rollback_seconds=0,  # Disable auto-rollback for tests
    )


@pytest.fixture
def live_engine() -> ChaosEngine:
    """Create a non-dry-run ChaosEngine for subprocess mocking tests."""
    return ChaosEngine(
        dry_run=False,
        namespace_allowlist=["chaos-lab"],
        max_concurrent=3,
        auto_rollback_seconds=0,
    )


# ── Create Experiment Tests ──────────────────────────────────────────


class TestCreateExperiment:
    def test_create_basic(self, engine: ChaosEngine):
        exp = engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")
        assert exp.type == ChaosType.POD_KILL
        assert exp.target_namespace == "chaos-lab"
        assert exp.status == ChaosStatus.PENDING
        assert exp.id is not None
        assert exp.name.startswith("pod_kill-")

    def test_create_with_params(self, engine: ChaosEngine):
        params = {"action": "scale-zero", "deployments": ["frontend"]}
        exp = engine.create_experiment(
            ChaosType.POD_KILL, "chaos-lab",
            params=params, name="custom-name", duration_seconds=120,
        )
        assert exp.name == "custom-name"
        assert exp.params == params
        assert exp.duration_seconds == 120

    def test_create_all_types(self, engine: ChaosEngine):
        for chaos_type in ChaosType:
            exp = engine.create_experiment(chaos_type, "chaos-lab")
            assert exp.type == chaos_type
            assert exp.status == ChaosStatus.PENDING

    def test_create_namespace_not_allowed(self, engine: ChaosEngine):
        with pytest.raises(NamespaceNotAllowed, match="not in allowlist"):
            engine.create_experiment(ChaosType.POD_KILL, "production")

    def test_create_allowed_namespace(self, engine: ChaosEngine):
        exp = engine.create_experiment(ChaosType.POD_KILL, "test-ns")
        assert exp.target_namespace == "test-ns"

    def test_created_at_is_set(self, engine: ChaosEngine):
        exp = engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")
        assert isinstance(exp.created_at, datetime)
        assert exp.created_at.tzinfo is not None


# ── Get / List / Delete Tests ────────────────────────────────────────


class TestExperimentCRUD:
    def test_get_experiment(self, engine: ChaosEngine):
        exp = engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")
        retrieved = engine.get_experiment(exp.id)
        assert retrieved.id == exp.id

    def test_get_experiment_not_found(self, engine: ChaosEngine):
        with pytest.raises(ExperimentNotFound):
            engine.get_experiment("nonexistent-id")

    def test_list_experiments(self, engine: ChaosEngine):
        engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")
        engine.create_experiment(ChaosType.NETWORK_BLOCK, "chaos-lab")
        experiments = engine.list_experiments()
        assert len(experiments) == 2

    def test_list_experiments_empty(self, engine: ChaosEngine):
        assert engine.list_experiments() == []

    def test_delete_experiment(self, engine: ChaosEngine):
        exp = engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")
        assert engine.delete_experiment(exp.id) is True
        assert engine.list_experiments() == []

    def test_delete_experiment_not_found(self, engine: ChaosEngine):
        with pytest.raises(ExperimentNotFound):
            engine.delete_experiment("nonexistent-id")

    def test_delete_running_experiment_fails(self, engine: ChaosEngine):
        exp = engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")
        # Dry-run experiment completes immediately, so manually set status
        engine._experiments[exp.id].status = ChaosStatus.RUNNING
        with pytest.raises(ChaosEngineError, match="Cannot delete a running"):
            engine.delete_experiment(exp.id)


# ── Run Experiment Tests ─────────────────────────────────────────────


class TestRunExperiment:
    def test_run_dry_run(self, engine: ChaosEngine):
        exp = engine.create_experiment(ChaosType.RESOURCE_STRESS, "chaos-lab")
        result = engine.run_experiment(exp.id)
        assert result.status == ChaosStatus.COMPLETED
        assert result.experiment_id == exp.id
        assert any("DRY RUN" in obs for obs in result.observations)
        assert result.start_time is not None
        assert result.end_time is not None

    def test_run_not_found(self, engine: ChaosEngine):
        with pytest.raises(ExperimentNotFound):
            engine.run_experiment("nonexistent-id")

    def test_run_not_pending(self, engine: ChaosEngine):
        exp = engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")
        engine.run_experiment(exp.id)  # Runs and completes (dry run)
        with pytest.raises(ChaosEngineError, match="expected 'pending'"):
            engine.run_experiment(exp.id)

    def test_run_max_concurrent_exceeded(self, engine: ChaosEngine):
        # Manually set 2 experiments to RUNNING
        e1 = engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")
        e2 = engine.create_experiment(ChaosType.NETWORK_BLOCK, "chaos-lab")
        e3 = engine.create_experiment(ChaosType.CONFIG_BREAK, "chaos-lab")
        engine._experiments[e1.id].status = ChaosStatus.RUNNING
        engine._experiments[e2.id].status = ChaosStatus.RUNNING
        with pytest.raises(MaxConcurrentExceeded):
            engine.run_experiment(e3.id)

    def test_run_all_scenario_types_dry_run(self, engine: ChaosEngine):
        for chaos_type in ChaosType:
            exp = engine.create_experiment(chaos_type, "chaos-lab")
            result = engine.run_experiment(exp.id)
            assert result.status == ChaosStatus.COMPLETED

    @patch("src.chaos.scenarios.subprocess.run")
    @patch("src.chaos.scenarios._run_kubectl")
    def test_run_resource_stress_live(self, mock_kubectl, mock_subprocess, live_engine):
        mock_subprocess.return_value = MagicMock(
            returncode=0, stdout="pod/stress-test created", stderr=""
        )
        exp = live_engine.create_experiment(
            ChaosType.RESOURCE_STRESS, "chaos-lab",
            params={"cpu": 1, "vm_bytes": "256M", "timeout_seconds": 60},
        )
        result = live_engine.run_experiment(exp.id)
        assert result.status == ChaosStatus.COMPLETED
        assert any("stress-ng" in obs for obs in result.observations)
        mock_subprocess.assert_called_once()

    @patch("src.chaos.scenarios._run_kubectl")
    def test_run_network_block_live(self, mock_kubectl, live_engine):
        mock_kubectl.return_value = MagicMock(
            returncode=0, stdout="networkpolicy created", stderr=""
        )
        # NetworkBlockScenario uses subprocess.run directly
        with patch("src.chaos.scenarios.subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(
                returncode=0, stdout="networkpolicy/chaos-block-backend created", stderr=""
            )
            exp = live_engine.create_experiment(ChaosType.NETWORK_BLOCK, "chaos-lab")
            result = live_engine.run_experiment(exp.id)
            assert result.status == ChaosStatus.COMPLETED

    @patch("src.chaos.scenarios._run_kubectl")
    def test_run_pod_kill_live(self, mock_kubectl, live_engine):
        mock_kubectl.return_value = MagicMock(
            returncode=0, stdout="pod deleted", stderr=""
        )
        exp = live_engine.create_experiment(
            ChaosType.POD_KILL, "chaos-lab", params={"action": "kill"},
        )
        result = live_engine.run_experiment(exp.id)
        assert result.status == ChaosStatus.COMPLETED

    @patch("src.chaos.scenarios._run_kubectl")
    def test_run_pod_kill_scale_zero(self, mock_kubectl, live_engine):
        mock_kubectl.return_value = MagicMock(
            returncode=0, stdout="deployment scaled", stderr=""
        )
        exp = live_engine.create_experiment(
            ChaosType.POD_KILL, "chaos-lab",
            params={"action": "scale-zero", "deployments": ["frontend", "backend"]},
        )
        result = live_engine.run_experiment(exp.id)
        assert result.status == ChaosStatus.COMPLETED
        # Should have scaled 2 deployments
        assert mock_kubectl.call_count == 2

    @patch("src.chaos.scenarios._run_kubectl")
    def test_run_config_break_bad_image(self, mock_kubectl, live_engine):
        mock_kubectl.return_value = MagicMock(
            returncode=0, stdout="image updated", stderr=""
        )
        exp = live_engine.create_experiment(
            ChaosType.CONFIG_BREAK, "chaos-lab",
            params={"action": "bad-image"},
        )
        result = live_engine.run_experiment(exp.id)
        assert result.status == ChaosStatus.COMPLETED

    @patch("src.chaos.scenarios._run_kubectl")
    def test_run_node_drain_live(self, mock_kubectl, live_engine):
        # First call: get node name. Second: cordon. Third: drain.
        mock_kubectl.side_effect = [
            MagicMock(returncode=0, stdout="ip-10-0-1-1", stderr=""),
            MagicMock(returncode=0, stdout="node cordoned", stderr=""),
            MagicMock(returncode=0, stdout="node drained", stderr=""),
        ]
        exp = live_engine.create_experiment(ChaosType.NODE_DRAIN, "chaos-lab")
        result = live_engine.run_experiment(exp.id)
        assert result.status == ChaosStatus.COMPLETED
        assert any("Cordoned" in obs for obs in result.observations)
        assert any("Drained" in obs for obs in result.observations)

    @patch("src.chaos.scenarios._run_kubectl")
    def test_run_failure_triggers_rollback(self, mock_kubectl, live_engine):
        # Simulate execution failure then rollback success
        mock_kubectl.side_effect = [
            subprocess.CalledProcessError(1, "kubectl", stderr="connection refused"),
            MagicMock(returncode=0, stdout="cleaned up", stderr=""),
        ]
        # PodKill with kill action uses _run_kubectl which will raise
        exp = live_engine.create_experiment(
            ChaosType.POD_KILL, "chaos-lab", params={"action": "kill"},
        )
        result = live_engine.run_experiment(exp.id)
        assert result.status == ChaosStatus.FAILED
        assert result.rollback_performed is True


# ── Rollback Tests ───────────────────────────────────────────────────


class TestRollbackExperiment:
    def test_rollback_dry_run(self, engine: ChaosEngine):
        exp = engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")
        engine.run_experiment(exp.id)
        success = engine.rollback_experiment(exp.id)
        assert success is True
        assert engine.get_experiment(exp.id).status == ChaosStatus.ROLLED_BACK

    def test_rollback_not_found(self, engine: ChaosEngine):
        with pytest.raises(ExperimentNotFound):
            engine.rollback_experiment("nonexistent-id")

    @patch("src.chaos.scenarios._run_kubectl")
    def test_rollback_resource_stress(self, mock_kubectl, live_engine):
        mock_kubectl.return_value = MagicMock(
            returncode=0, stdout="pod deleted", stderr=""
        )
        with patch("src.chaos.scenarios.subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(
                returncode=0, stdout="pod/stress-test created", stderr=""
            )
            exp = live_engine.create_experiment(ChaosType.RESOURCE_STRESS, "chaos-lab")
            live_engine.run_experiment(exp.id)

        mock_kubectl.return_value = MagicMock(
            returncode=0, stdout="pod deleted", stderr=""
        )
        success = live_engine.rollback_experiment(exp.id)
        assert success is True

    @patch("src.chaos.scenarios._run_kubectl")
    def test_rollback_network_block(self, mock_kubectl, live_engine):
        with patch("src.chaos.scenarios.subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(
                returncode=0, stdout="networkpolicy created", stderr=""
            )
            exp = live_engine.create_experiment(ChaosType.NETWORK_BLOCK, "chaos-lab")
            live_engine.run_experiment(exp.id)

        mock_kubectl.return_value = MagicMock(
            returncode=0, stdout="networkpolicy deleted", stderr=""
        )
        success = live_engine.rollback_experiment(exp.id)
        assert success is True

    @patch("src.chaos.scenarios._run_kubectl")
    def test_rollback_pod_kill(self, mock_kubectl, live_engine):
        mock_kubectl.return_value = MagicMock(
            returncode=0, stdout="scaled", stderr=""
        )
        exp = live_engine.create_experiment(
            ChaosType.POD_KILL, "chaos-lab",
            params={"action": "scale-zero", "original_replicas": {"frontend": 3}},
        )
        live_engine.run_experiment(exp.id)
        success = live_engine.rollback_experiment(exp.id)
        assert success is True

    @patch("src.chaos.scenarios._run_kubectl")
    def test_rollback_node_drain(self, mock_kubectl, live_engine):
        mock_kubectl.side_effect = [
            # execute: get_first_node, cordon, drain
            MagicMock(returncode=0, stdout="node-1", stderr=""),
            MagicMock(returncode=0, stdout="cordoned", stderr=""),
            MagicMock(returncode=0, stdout="drained", stderr=""),
            # rollback: get_all_nodes, uncordon
            MagicMock(returncode=0, stdout="node-1 node-2", stderr=""),
            MagicMock(returncode=0, stdout="uncordoned", stderr=""),
            MagicMock(returncode=0, stdout="uncordoned", stderr=""),
        ]
        exp = live_engine.create_experiment(ChaosType.NODE_DRAIN, "chaos-lab")
        live_engine.run_experiment(exp.id)
        success = live_engine.rollback_experiment(exp.id)
        assert success is True


# ── Safety Guards Tests ──────────────────────────────────────────────


class TestSafetyGuards:
    def test_namespace_allowlist(self, engine: ChaosEngine):
        assert "chaos-lab" in engine.namespace_allowlist
        assert "test-ns" in engine.namespace_allowlist
        with pytest.raises(NamespaceNotAllowed):
            engine.create_experiment(ChaosType.POD_KILL, "kube-system")

    def test_dry_run_mode(self, engine: ChaosEngine):
        assert engine.dry_run is True
        exp = engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")
        result = engine.run_experiment(exp.id)
        assert any("DRY RUN" in obs for obs in result.observations)

    def test_max_concurrent_limit(self, engine: ChaosEngine):
        assert engine.max_concurrent == 2
        e1 = engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")
        e2 = engine.create_experiment(ChaosType.NETWORK_BLOCK, "chaos-lab")
        e3 = engine.create_experiment(ChaosType.CONFIG_BREAK, "chaos-lab")
        # Artificially set as running
        engine._experiments[e1.id].status = ChaosStatus.RUNNING
        engine._experiments[e2.id].status = ChaosStatus.RUNNING
        with pytest.raises(MaxConcurrentExceeded):
            engine.run_experiment(e3.id)

    def test_auto_rollback_disabled(self, engine: ChaosEngine):
        assert engine.auto_rollback_seconds == 0

    def test_engine_default_config(self):
        e = ChaosEngine()
        assert e.dry_run is True  # safe default: dry_run=True
        assert e.namespace_allowlist == ["chaos-lab"]
        assert e.max_concurrent == 3
        assert e.auto_rollback_seconds == 600


# ── Get Result Tests ─────────────────────────────────────────────────


class TestGetResult:
    def test_get_result_after_run(self, engine: ChaosEngine):
        exp = engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")
        engine.run_experiment(exp.id)
        result = engine.get_result(exp.id)
        assert result is not None
        assert result.experiment_id == exp.id

    def test_get_result_no_run(self, engine: ChaosEngine):
        exp = engine.create_experiment(ChaosType.POD_KILL, "chaos-lab")
        result = engine.get_result(exp.id)
        assert result is None
