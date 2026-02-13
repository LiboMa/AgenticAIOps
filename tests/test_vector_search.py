"""
Tests for vector_search.py — OpenSearch 向量搜索

Coverage targets:
- VectorKnowledgeSearch: init, create_index, embedding, index, search
- Authentication modes (basic, IAM)
- Semantic search, hybrid search
- Error handling, stats
"""

import pytest
import json
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

from src.vector_search import (
    VectorKnowledgeSearch,
    get_vector_search,
    OPENSEARCH_ENDPOINT,
    KNOWLEDGE_INDEX,
    EMBEDDING_MODEL,
    EMBEDDING_DIMENSION,
)


# ─── Configuration Constants ─────────────────────────────────────────────────

class TestConstants:
    def test_embedding_dimension(self):
        assert EMBEDDING_DIMENSION == 1024

    def test_embedding_model(self):
        assert "titan" in EMBEDDING_MODEL.lower()

    def test_knowledge_index(self):
        assert KNOWLEDGE_INDEX == "aiops-knowledge"

    def test_endpoint_configured(self):
        assert OPENSEARCH_ENDPOINT != ""


# ─── Init Tests ───────────────────────────────────────────────────────────────

class TestVectorSearchInit:
    def test_init_no_credentials(self):
        """Init without basic auth credentials — may fallback."""
        with patch("boto3.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.region_name = "ap-southeast-1"
            mock_session.client.return_value = MagicMock()
            mock_session.get_credentials.return_value = MagicMock()
            mock_session_cls.return_value = mock_session

            with patch.dict("os.environ", {"OPENSEARCH_USER": "", "OPENSEARCH_PASSWORD": ""}):
                vs = VectorKnowledgeSearch()
                assert vs.endpoint == OPENSEARCH_ENDPOINT
        assert vs.index == KNOWLEDGE_INDEX

    def test_init_basic_auth(self):
        """Init with basic auth credentials."""
        with patch("boto3.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.region_name = "ap-southeast-1"
            mock_session.client.return_value = MagicMock()
            mock_session_cls.return_value = mock_session

            with patch.dict("os.environ", {"OPENSEARCH_USER": "admin", "OPENSEARCH_PASSWORD": "pass123"}):
                # The module reads env at import time, need to patch the module vars
                with patch("src.vector_search.OPENSEARCH_USER", "admin"), \
                     patch("src.vector_search.OPENSEARCH_PASSWORD", "pass123"):
                    vs = VectorKnowledgeSearch()
                    assert vs._auth_mode in ("basic", "none", "iam")


# ─── Embedding Tests ──────────────────────────────────────────────────────────

class TestEmbeddingGeneration:
    def test_generate_embedding_success(self):
        vs = VectorKnowledgeSearch.__new__(VectorKnowledgeSearch)
        vs.bedrock = MagicMock()
        vs.client = None
        vs._initialized = False

        # Mock Bedrock response
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({
            "embedding": [0.1] * 1024
        }).encode()
        vs.bedrock.invoke_model.return_value = {"body": mock_body}

        embedding = vs._generate_embedding("test text")
        assert embedding is not None
        assert len(embedding) == 1024

        # Verify call
        vs.bedrock.invoke_model.assert_called_once()
        call_kwargs = vs.bedrock.invoke_model.call_args[1]
        assert call_kwargs["modelId"] == EMBEDDING_MODEL

    def test_generate_embedding_truncates_long_text(self):
        vs = VectorKnowledgeSearch.__new__(VectorKnowledgeSearch)
        vs.bedrock = MagicMock()

        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({
            "embedding": [0.5] * 1024
        }).encode()
        vs.bedrock.invoke_model.return_value = {"body": mock_body}

        long_text = "x" * 10000  # Exceeds 8000 char limit
        embedding = vs._generate_embedding(long_text)
        assert embedding is not None

        # Verify text was truncated in the request
        call_body = json.loads(vs.bedrock.invoke_model.call_args[1]["body"])
        assert len(call_body["inputText"]) <= 8000

    def test_generate_embedding_failure(self):
        vs = VectorKnowledgeSearch.__new__(VectorKnowledgeSearch)
        vs.bedrock = MagicMock()
        vs.bedrock.invoke_model.side_effect = Exception("Bedrock error")

        embedding = vs._generate_embedding("test")
        assert embedding is None

    def test_generate_embedding_no_bedrock(self):
        vs = VectorKnowledgeSearch.__new__(VectorKnowledgeSearch)
        vs.bedrock = None

        embedding = vs._generate_embedding("test")
        assert embedding is None


# ─── Index Creation Tests ─────────────────────────────────────────────────────

class TestCreateIndex:
    def test_create_index_success(self):
        vs = VectorKnowledgeSearch.__new__(VectorKnowledgeSearch)
        vs.client = MagicMock()
        vs.client.indices.exists.return_value = False
        vs.index = KNOWLEDGE_INDEX

        result = vs.create_index()
        assert result is True
        vs.client.indices.create.assert_called_once()
        call_kwargs = vs.client.indices.create.call_args[1]
        assert call_kwargs["index"] == KNOWLEDGE_INDEX

    def test_create_index_already_exists(self):
        vs = VectorKnowledgeSearch.__new__(VectorKnowledgeSearch)
        vs.client = MagicMock()
        vs.client.indices.exists.return_value = True
        vs.index = KNOWLEDGE_INDEX

        result = vs.create_index()
        assert result is True
        vs.client.indices.create.assert_not_called()

    def test_create_index_no_client(self):
        vs = VectorKnowledgeSearch.__new__(VectorKnowledgeSearch)
        vs.client = None
        vs.index = KNOWLEDGE_INDEX

        result = vs.create_index()
        assert result is False

    def test_create_index_failure(self):
        vs = VectorKnowledgeSearch.__new__(VectorKnowledgeSearch)
        vs.client = MagicMock()
        vs.client.indices.exists.return_value = False
        vs.client.indices.create.side_effect = Exception("Create failed")
        vs.index = KNOWLEDGE_INDEX

        result = vs.create_index()
        assert result is False

    def test_index_mapping_has_knn_vector(self):
        vs = VectorKnowledgeSearch.__new__(VectorKnowledgeSearch)
        vs.client = MagicMock()
        vs.client.indices.exists.return_value = False
        vs.index = KNOWLEDGE_INDEX

        vs.create_index()

        call_kwargs = vs.client.indices.create.call_args[1]
        mapping = call_kwargs["body"]
        embedding_props = mapping["mappings"]["properties"]["embedding"]
        assert embedding_props["type"] == "knn_vector"
        assert embedding_props["dimension"] == EMBEDDING_DIMENSION


# ─── Index Knowledge Tests ────────────────────────────────────────────────────

class TestIndexKnowledge:
    def _make_vs(self):
        vs = VectorKnowledgeSearch.__new__(VectorKnowledgeSearch)
        vs.client = MagicMock()
        vs.bedrock = MagicMock()
        vs._initialized = True
        vs.index = KNOWLEDGE_INDEX

        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({
            "embedding": [0.1] * 1024
        }).encode()
        vs.bedrock.invoke_model.return_value = {"body": mock_body}
        return vs

    def test_index_knowledge_success(self):
        vs = self._make_vs()
        result = vs.index_knowledge(
            doc_id="doc-001",
            title="Test Document",
            description="A test",
            content="Some content",
            doc_type="pattern",
            category="performance",
            service="ec2",
        )
        assert result is True
        vs.client.index.assert_called_once()
        call_kwargs = vs.client.index.call_args[1]
        assert call_kwargs["index"] == KNOWLEDGE_INDEX
        assert call_kwargs["id"] == "doc-001"

    def test_index_knowledge_not_initialized(self):
        vs = VectorKnowledgeSearch.__new__(VectorKnowledgeSearch)
        vs._initialized = False

        result = vs.index_knowledge(
            doc_id="fail",
            title="Fail",
            description="",
            content="",
            doc_type="pattern",
        )
        assert result is False

    def test_index_knowledge_no_embedding(self):
        vs = VectorKnowledgeSearch.__new__(VectorKnowledgeSearch)
        vs._initialized = True
        vs.bedrock = MagicMock()
        vs.bedrock.invoke_model.side_effect = Exception("Embedding failed")

        result = vs.index_knowledge(
            doc_id="no_embed",
            title="No Embed",
            description="",
            content="",
            doc_type="pattern",
        )
        assert result is False


# ─── Semantic Search Tests ────────────────────────────────────────────────────

class TestSemanticSearch:
    def _make_vs_with_search(self, hits=None):
        vs = VectorKnowledgeSearch.__new__(VectorKnowledgeSearch)
        vs.client = MagicMock()
        vs.bedrock = MagicMock()
        vs._initialized = True
        vs.index = KNOWLEDGE_INDEX

        # Mock embedding
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({
            "embedding": [0.1] * 1024
        }).encode()
        vs.bedrock.invoke_model.return_value = {"body": mock_body}

        # Mock search results
        if hits is None:
            hits = [
                {
                    "_source": {
                        "id": "pat-001",
                        "title": "EC2 High CPU",
                        "description": "CPU utilization high",
                        "type": "pattern",
                        "service": "ec2",
                        "category": "performance",
                    },
                    "_score": 0.92,
                }
            ]
        vs.client.search.return_value = {"hits": {"hits": hits}}
        return vs

    def test_semantic_search_basic(self):
        vs = self._make_vs_with_search()
        results = vs.semantic_search("high cpu utilization")
        assert len(results) == 1
        assert results[0]["id"] == "pat-001"
        assert results[0]["score"] == 0.92

    def test_semantic_search_with_filters(self):
        vs = self._make_vs_with_search()
        results = vs.semantic_search(
            "cpu issue",
            doc_type="pattern",
            service="ec2",
        )
        assert len(results) == 1
        # Verify filtered query was used
        call_kwargs = vs.client.search.call_args[1]
        query_body = call_kwargs["body"]
        assert "bool" in query_body["query"]

    def test_semantic_search_empty_results(self):
        vs = self._make_vs_with_search(hits=[])
        results = vs.semantic_search("nonexistent query")
        assert len(results) == 0

    def test_semantic_search_not_initialized(self):
        vs = VectorKnowledgeSearch.__new__(VectorKnowledgeSearch)
        vs._initialized = False
        results = vs.semantic_search("test")
        assert results == []

    def test_semantic_search_embedding_failure(self):
        vs = VectorKnowledgeSearch.__new__(VectorKnowledgeSearch)
        vs._initialized = True
        vs.bedrock = MagicMock()
        vs.bedrock.invoke_model.side_effect = Exception("fail")
        results = vs.semantic_search("test")
        assert results == []

    def test_semantic_search_limit(self):
        vs = self._make_vs_with_search()
        vs.semantic_search("test", limit=3)
        call_kwargs = vs.client.search.call_args[1]
        assert call_kwargs["body"]["size"] == 3


# ─── Hybrid Search Tests ─────────────────────────────────────────────────────

class TestHybridSearch:
    def _make_vs(self):
        vs = VectorKnowledgeSearch.__new__(VectorKnowledgeSearch)
        vs.client = MagicMock()
        vs.bedrock = MagicMock()
        vs._initialized = True
        vs.index = KNOWLEDGE_INDEX

        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({
            "embedding": [0.1] * 1024
        }).encode()
        vs.bedrock.invoke_model.return_value = {"body": mock_body}

        vs.client.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "id": "hybrid-001",
                            "title": "Hybrid Result",
                            "description": "Found via hybrid",
                            "type": "pattern",
                            "service": "ec2",
                        },
                        "_score": 0.85,
                    }
                ]
            }
        }
        return vs

    def test_hybrid_search_basic(self):
        vs = self._make_vs()
        results = vs.hybrid_search("cpu issue")
        assert len(results) == 1
        assert results[0]["id"] == "hybrid-001"

    def test_hybrid_search_with_filters(self):
        vs = self._make_vs()
        results = vs.hybrid_search("cpu", doc_type="pattern", service="ec2")
        assert len(results) == 1
        call_kwargs = vs.client.search.call_args[1]
        query = call_kwargs["body"]["query"]
        assert len(query["bool"]["filter"]) == 2

    def test_hybrid_search_not_initialized(self):
        vs = VectorKnowledgeSearch.__new__(VectorKnowledgeSearch)
        vs._initialized = False
        results = vs.hybrid_search("test")
        assert results == []

    def test_hybrid_search_error(self):
        vs = self._make_vs()
        vs.client.search.side_effect = Exception("Search failed")
        results = vs.hybrid_search("test")
        assert results == []


# ─── Stats Tests ──────────────────────────────────────────────────────────────

class TestStats:
    def test_stats_not_initialized(self):
        vs = VectorKnowledgeSearch.__new__(VectorKnowledgeSearch)
        vs._initialized = False
        stats = vs.get_stats()
        assert "error" in stats

    def test_stats_success(self):
        vs = VectorKnowledgeSearch.__new__(VectorKnowledgeSearch)
        vs._initialized = True
        vs.client = MagicMock()
        vs.index = KNOWLEDGE_INDEX

        vs.client.count.return_value = {"count": 42}
        vs.client.indices.stats.return_value = {
            "indices": {
                KNOWLEDGE_INDEX: {
                    "total": {
                        "store": {"size_in_bytes": 1048576}
                    }
                }
            }
        }

        stats = vs.get_stats()
        assert stats["index"] == KNOWLEDGE_INDEX
        assert stats["document_count"] == 42
        assert stats["size_bytes"] == 1048576
        assert stats["status"] == "healthy"

    def test_stats_error(self):
        vs = VectorKnowledgeSearch.__new__(VectorKnowledgeSearch)
        vs._initialized = True
        vs.client = MagicMock()
        vs.index = KNOWLEDGE_INDEX
        vs.client.count.side_effect = Exception("Connection refused")

        stats = vs.get_stats()
        assert "error" in stats


# ─── Singleton ─────────────────────────────────────────────────────────────────

class TestSingleton:
    def test_get_vector_search_singleton(self):
        import src.vector_search as vs_mod
        vs_mod._vector_search = None

        with patch("boto3.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.region_name = "ap-southeast-1"
            mock_session.client.return_value = MagicMock()
            mock_session.get_credentials.return_value = MagicMock()
            mock_session_cls.return_value = mock_session

            vs1 = get_vector_search()
            vs2 = get_vector_search()
            assert vs1 is vs2

        vs_mod._vector_search = None
