"""Tests for Chaos API endpoints — mock engine, no real kubectl calls."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.chaos.api import router, set_engine, get_engine
from src.chaos.engine import ChaosEngine
from src.chaos.models import ChaosStatus, ChaosType


@pytest.fixture
def app():
    """Create a minimal FastAPI app with the chaos router."""
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def engine():
    """Create a dry-run engine and install it."""
    e = ChaosEngine(
        dry_run=True,
        namespace_allowlist=["chaos-lab", "test-ns"],
        max_concurrent=3,
        auto_rollback_seconds=0,
    )
    set_engine(e)
    yield e


@pytest.fixture
def client(app, engine):
    """Create a test client with the dry-run engine."""
    return TestClient(app)


# ── Create Experiment ────────────────────────────────────────────────


class TestCreateExperimentAPI:
    def test_create_success(self, client):
        resp = client.post("/api/chaos/experiments", json={
            "name": "test-stress",
            "type": "resource_stress",
            "target_namespace": "chaos-lab",
            "duration_seconds": 120,
            "params": {"cpu": 1},
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "test-stress"
        assert data["type"] == "resource_stress"
        assert data["status"] == "pending"
        assert "id" in data

    def test_create_all_types(self, client):
        for ct in ChaosType:
            resp = client.post("/api/chaos/experiments", json={
                "name": f"test-{ct.value}",
                "type": ct.value,
            })
            assert resp.status_code == 201

    def test_create_namespace_forbidden(self, client):
        resp = client.post("/api/chaos/experiments", json={
            "name": "bad-ns",
            "type": "pod_kill",
            "target_namespace": "production",
        })
        assert resp.status_code == 403
        assert "not in allowlist" in resp.json()["detail"]

    def test_create_invalid_type(self, client):
        resp = client.post("/api/chaos/experiments", json={
            "name": "bad-type",
            "type": "invalid_type",
        })
        assert resp.status_code == 422  # Pydantic validation error

    def test_create_default_namespace(self, client):
        resp = client.post("/api/chaos/experiments", json={
            "name": "default-ns",
            "type": "pod_kill",
        })
        assert resp.status_code == 201
        assert resp.json()["target_namespace"] == "chaos-lab"


# ── Run Experiment ───────────────────────────────────────────────────


class TestRunExperimentAPI:
    def _create(self, client, chaos_type="pod_kill"):
        resp = client.post("/api/chaos/experiments", json={
            "name": "run-test",
            "type": chaos_type,
        })
        return resp.json()["id"]

    def test_run_success(self, client):
        exp_id = self._create(client)
        resp = client.post(f"/api/chaos/experiments/{exp_id}/run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["experiment_id"] == exp_id
        assert data["status"] == "completed"
        assert any("DRY RUN" in obs for obs in data["observations"])

    def test_run_all_types(self, client):
        for ct in ChaosType:
            exp_id = self._create(client, ct.value)
            resp = client.post(f"/api/chaos/experiments/{exp_id}/run")
            assert resp.status_code == 200
            assert resp.json()["status"] == "completed"

    def test_run_not_found(self, client):
        resp = client.post("/api/chaos/experiments/nonexistent/run")
        assert resp.status_code == 404

    def test_run_already_run(self, client):
        exp_id = self._create(client)
        client.post(f"/api/chaos/experiments/{exp_id}/run")
        resp = client.post(f"/api/chaos/experiments/{exp_id}/run")
        assert resp.status_code == 400
        assert "expected 'pending'" in resp.json()["detail"]


# ── Rollback Experiment ──────────────────────────────────────────────


class TestRollbackExperimentAPI:
    def _create_and_run(self, client, chaos_type="pod_kill"):
        resp = client.post("/api/chaos/experiments", json={
            "name": "rollback-test",
            "type": chaos_type,
        })
        exp_id = resp.json()["id"]
        client.post(f"/api/chaos/experiments/{exp_id}/run")
        return exp_id

    def test_rollback_success(self, client):
        exp_id = self._create_and_run(client)
        resp = client.post(f"/api/chaos/experiments/{exp_id}/rollback")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_rollback_not_found(self, client):
        resp = client.post("/api/chaos/experiments/nonexistent/rollback")
        assert resp.status_code == 404

    def test_rollback_changes_status(self, client):
        exp_id = self._create_and_run(client)
        client.post(f"/api/chaos/experiments/{exp_id}/rollback")
        resp = client.get(f"/api/chaos/experiments/{exp_id}")
        assert resp.json()["status"] == "rolled_back"


# ── List Experiments ─────────────────────────────────────────────────


class TestListExperimentsAPI:
    def test_list_empty(self, client):
        resp = client.get("/api/chaos/experiments")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_multiple(self, client):
        client.post("/api/chaos/experiments", json={
            "name": "exp-1", "type": "pod_kill",
        })
        client.post("/api/chaos/experiments", json={
            "name": "exp-2", "type": "network_block",
        })
        resp = client.get("/api/chaos/experiments")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


# ── Get Experiment ───────────────────────────────────────────────────


class TestGetExperimentAPI:
    def test_get_success(self, client):
        resp = client.post("/api/chaos/experiments", json={
            "name": "get-test", "type": "pod_kill",
        })
        exp_id = resp.json()["id"]
        resp = client.get(f"/api/chaos/experiments/{exp_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "get-test"

    def test_get_not_found(self, client):
        resp = client.get("/api/chaos/experiments/nonexistent")
        assert resp.status_code == 404


# ── Delete Experiment ────────────────────────────────────────────────


class TestDeleteExperimentAPI:
    def test_delete_success(self, client):
        resp = client.post("/api/chaos/experiments", json={
            "name": "delete-test", "type": "pod_kill",
        })
        exp_id = resp.json()["id"]
        resp = client.delete(f"/api/chaos/experiments/{exp_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

        # Verify it's gone
        resp = client.get(f"/api/chaos/experiments/{exp_id}")
        assert resp.status_code == 404

    def test_delete_not_found(self, client):
        resp = client.delete("/api/chaos/experiments/nonexistent")
        assert resp.status_code == 404

    def test_delete_running_experiment(self, client, engine):
        resp = client.post("/api/chaos/experiments", json={
            "name": "running-exp", "type": "pod_kill",
        })
        exp_id = resp.json()["id"]
        # Manually set to running
        engine._experiments[exp_id].status = ChaosStatus.RUNNING
        resp = client.delete(f"/api/chaos/experiments/{exp_id}")
        assert resp.status_code == 400
        assert "Cannot delete" in resp.json()["detail"]


# ── Integration: Full Lifecycle ──────────────────────────────────────


class TestFullLifecycle:
    def test_create_run_rollback_delete(self, client):
        # Create
        resp = client.post("/api/chaos/experiments", json={
            "name": "lifecycle-test",
            "type": "resource_stress",
            "params": {"cpu": 1},
        })
        assert resp.status_code == 201
        exp_id = resp.json()["id"]

        # Verify pending
        resp = client.get(f"/api/chaos/experiments/{exp_id}")
        assert resp.json()["status"] == "pending"

        # Run
        resp = client.post(f"/api/chaos/experiments/{exp_id}/run")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

        # Rollback
        resp = client.post(f"/api/chaos/experiments/{exp_id}/rollback")
        assert resp.status_code == 200

        # Verify rolled back
        resp = client.get(f"/api/chaos/experiments/{exp_id}")
        assert resp.json()["status"] == "rolled_back"

        # Delete
        resp = client.delete(f"/api/chaos/experiments/{exp_id}")
        assert resp.status_code == 200

        # Verify gone
        resp = client.get(f"/api/chaos/experiments/{exp_id}")
        assert resp.status_code == 404
