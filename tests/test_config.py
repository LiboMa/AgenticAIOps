"""
Tests for src/config.py — Centralized configuration

Coverage target: 80%+ (from 0%)
"""

import os
import pytest
from unittest.mock import patch


class TestAvailableModels:
    """Test model configuration constants."""

    def test_available_models_has_haiku(self):
        from src.config import AVAILABLE_MODELS
        assert "haiku" in AVAILABLE_MODELS
        assert "anthropic.claude" in AVAILABLE_MODELS["haiku"]

    def test_available_models_has_sonnet(self):
        from src.config import AVAILABLE_MODELS
        assert "sonnet" in AVAILABLE_MODELS

    def test_available_models_has_opus(self):
        from src.config import AVAILABLE_MODELS
        assert "opus" in AVAILABLE_MODELS

    def test_available_models_has_legacy(self):
        from src.config import AVAILABLE_MODELS
        assert "haiku-3" in AVAILABLE_MODELS
        assert "sonnet-3" in AVAILABLE_MODELS


class TestGetModelId:
    """Test get_model_id() function."""

    def test_get_model_id_haiku(self):
        from src.config import get_model_id, AVAILABLE_MODELS
        result = get_model_id("haiku")
        assert result == AVAILABLE_MODELS["haiku"]

    def test_get_model_id_sonnet(self):
        from src.config import get_model_id, AVAILABLE_MODELS
        result = get_model_id("sonnet")
        assert result == AVAILABLE_MODELS["sonnet"]

    def test_get_model_id_opus(self):
        from src.config import get_model_id, AVAILABLE_MODELS
        result = get_model_id("opus")
        assert result == AVAILABLE_MODELS["opus"]

    def test_get_model_id_case_insensitive(self):
        from src.config import get_model_id, AVAILABLE_MODELS
        assert get_model_id("HAIKU") == AVAILABLE_MODELS["haiku"]
        assert get_model_id("Sonnet") == AVAILABLE_MODELS["sonnet"]

    def test_get_model_id_full_id_passthrough_anthropic(self):
        from src.config import get_model_id
        full_id = "anthropic.claude-v2"
        assert get_model_id(full_id) == full_id

    def test_get_model_id_full_id_passthrough_apac(self):
        from src.config import get_model_id
        full_id = "apac.anthropic.claude-3-haiku-20240307-v1:0"
        assert get_model_id(full_id) == full_id

    def test_get_model_id_unknown_falls_back_to_haiku(self):
        from src.config import get_model_id, AVAILABLE_MODELS
        result = get_model_id("nonexistent-model")
        assert result == AVAILABLE_MODELS["haiku"]

    def test_get_model_id_none_uses_default(self):
        from src.config import get_model_id
        # Should not raise, uses DEFAULT_MODEL
        result = get_model_id(None)
        assert result  # non-empty string

    def test_get_model_id_legacy_models(self):
        from src.config import get_model_id, AVAILABLE_MODELS
        assert get_model_id("haiku-3") == AVAILABLE_MODELS["haiku-3"]
        assert get_model_id("sonnet-3") == AVAILABLE_MODELS["sonnet-3"]


class TestConfigConstants:
    """Test configuration constants and env var overrides."""

    def test_cluster_name_default(self):
        from src.config import CLUSTER_NAME
        assert isinstance(CLUSTER_NAME, str)
        assert len(CLUSTER_NAME) > 0

    def test_aws_region_default(self):
        from src.config import AWS_REGION
        assert isinstance(AWS_REGION, str)

    def test_api_host_default(self):
        from src.config import API_HOST
        assert isinstance(API_HOST, str)

    def test_api_port_default(self):
        from src.config import API_PORT
        assert isinstance(API_PORT, int)

    def test_knowledge_base_id(self):
        from src.config import KNOWLEDGE_BASE_ID
        assert isinstance(KNOWLEDGE_BASE_ID, str)

    def test_kb_s3_bucket(self):
        from src.config import KB_S3_BUCKET
        assert isinstance(KB_S3_BUCKET, str)
