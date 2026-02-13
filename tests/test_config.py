"""Tests for config module — model lookup, environment variables."""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestGetModelId:

    def test_short_name_haiku(self):
        from src.config import get_model_id, AVAILABLE_MODELS
        result = get_model_id("haiku")
        assert result == AVAILABLE_MODELS["haiku"]

    def test_short_name_sonnet(self):
        from src.config import get_model_id, AVAILABLE_MODELS
        result = get_model_id("sonnet")
        assert result == AVAILABLE_MODELS["sonnet"]

    def test_full_model_id_passthrough(self):
        from src.config import get_model_id
        full_id = "anthropic.claude-3-haiku-20240307-v1:0"
        assert get_model_id(full_id) == full_id

    def test_apac_prefix_passthrough(self):
        from src.config import get_model_id
        full_id = "apac.anthropic.claude-3-sonnet-20240229-v1:0"
        assert get_model_id(full_id) == full_id

    def test_unknown_name_defaults_haiku(self):
        from src.config import get_model_id, AVAILABLE_MODELS
        result = get_model_id("nonexistent")
        assert result == AVAILABLE_MODELS["haiku"]

    def test_none_uses_default(self):
        from src.config import get_model_id
        result = get_model_id(None)
        assert result  # Returns some model ID

    def test_case_insensitive(self):
        from src.config import get_model_id, AVAILABLE_MODELS
        assert get_model_id("Haiku") == AVAILABLE_MODELS["haiku"]
        assert get_model_id("SONNET") == AVAILABLE_MODELS["sonnet"]


class TestConstants:

    def test_available_models_not_empty(self):
        from src.config import AVAILABLE_MODELS
        assert len(AVAILABLE_MODELS) >= 3

    def test_cluster_name_default(self):
        from src.config import CLUSTER_NAME
        assert isinstance(CLUSTER_NAME, str)

    def test_aws_region_default(self):
        from src.config import AWS_REGION
        assert isinstance(AWS_REGION, str)
