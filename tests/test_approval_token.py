"""Tests for HMAC-based approval token module."""

import os
import time
import pytest

# Ensure we can import
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.approval_token import generate, verify, reset_cache, DEFAULT_TTL_SECONDS


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Reset cache and set a test secret for each test."""
    reset_cache()
    monkeypatch.setenv("APPROVAL_TOKEN_SECRET", "test-secret-key-for-unit-tests-1234")
    monkeypatch.delenv("APPROVAL_TOKEN_TTL", raising=False)
    yield
    reset_cache()


class TestGenerate:
    def test_returns_string_with_dot(self):
        token = generate("kubectl delete pod foo")
        assert isinstance(token, str)
        assert "." in token

    def test_format_timestamp_dot_hex(self):
        token = generate("test-action")
        ts, sig = token.split(".", 1)
        assert ts.isdigit()
        assert len(sig) == 64  # SHA256 hex

    def test_different_actions_produce_different_tokens(self):
        t1 = generate("action-a")
        t2 = generate("action-b")
        assert t1.split(".")[1] != t2.split(".")[1]

    def test_same_action_same_second_same_token(self):
        t1 = generate("same")
        t2 = generate("same")
        # Same second → same token (deterministic)
        assert t1 == t2


class TestVerify:
    def test_valid_token(self):
        action = "kubectl delete pod test"
        token = generate(action)
        ok, reason = verify(token, action)
        assert ok is True
        assert reason == "OK"

    def test_wrong_action_fails(self):
        token = generate("action-a")
        ok, reason = verify(token, "action-b")
        assert ok is False
        assert "mismatch" in reason.lower()

    def test_expired_token(self, monkeypatch):
        action = "test"
        token = generate(action)
        # Fast-forward time
        ts = int(token.split(".")[0])
        monkeypatch.setattr("src.approval_token.time.time", lambda: ts + DEFAULT_TTL_SECONDS + 1)
        ok, reason = verify(token, action)
        assert ok is False
        assert "expired" in reason.lower()

    def test_future_timestamp(self):
        future_ts = str(int(time.time()) + 9999)
        ok, reason = verify(f"{future_ts}.deadbeef", "test")
        assert ok is False
        assert "future" in reason.lower()

    def test_empty_token(self):
        ok, reason = verify("", "test")
        assert ok is False

    def test_no_dot_token(self):
        ok, reason = verify("nodothere", "test")
        assert ok is False

    def test_invalid_timestamp(self):
        ok, reason = verify("notanumber.abcdef", "test")
        assert ok is False
        assert "timestamp" in reason.lower()

    def test_tampered_signature(self):
        action = "test"
        token = generate(action)
        ts, sig = token.split(".", 1)
        tampered = ts + "." + ("0" * 64)
        ok, reason = verify(tampered, action)
        assert ok is False
        assert "mismatch" in reason.lower()


class TestSecretHandling:
    def test_missing_secret_raises(self, monkeypatch):
        reset_cache()
        monkeypatch.delenv("APPROVAL_TOKEN_SECRET", raising=False)
        ok, reason = verify("123.abc", "test")
        assert ok is False
        assert "not set" in reason.lower()

    def test_missing_secret_generate_raises(self, monkeypatch):
        reset_cache()
        monkeypatch.delenv("APPROVAL_TOKEN_SECRET", raising=False)
        with pytest.raises(ValueError, match="not set"):
            generate("test")

    def test_custom_ttl(self, monkeypatch):
        reset_cache()
        monkeypatch.setenv("APPROVAL_TOKEN_TTL", "10")
        action = "test"
        token = generate(action)
        ts = int(token.split(".")[0])
        # Within TTL
        monkeypatch.setattr("src.approval_token.time.time", lambda: ts + 9)
        reset_cache()
        monkeypatch.setenv("APPROVAL_TOKEN_SECRET", "test-secret-key-for-unit-tests-1234")
        monkeypatch.setenv("APPROVAL_TOKEN_TTL", "10")
        ok, _ = verify(token, action)
        assert ok is True

    def test_different_secret_fails(self, monkeypatch):
        action = "test"
        token = generate(action)
        reset_cache()
        monkeypatch.setenv("APPROVAL_TOKEN_SECRET", "completely-different-secret-key!!")
        ok, reason = verify(token, action)
        assert ok is False
        assert "mismatch" in reason.lower()
