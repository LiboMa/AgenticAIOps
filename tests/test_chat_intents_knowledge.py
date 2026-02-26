"""Tests for routers/chat_intents/knowledge.py — keyword routing + helpers."""

import pytest
from unittest.mock import patch, MagicMock


class TestKnowledgeHandle:

    @pytest.mark.asyncio
    async def test_no_match(self):
        from routers.chat_intents.knowledge import handle
        assert await handle("hello", "hello") is None

    @pytest.mark.parametrize("msg", ["kb stats", "knowledge stats", "知识库统计"])
    @pytest.mark.asyncio
    async def test_kb_stats(self, msg):
        with patch("routers.chat_intents.knowledge._kb_stats", return_value="stats"):
            from routers.chat_intents.knowledge import handle
            assert await handle(msg, msg.lower()) == "stats"

    @pytest.mark.parametrize("msg", ["kb semantic high cpu", "semantic search timeout", "语义搜索 问题"])
    @pytest.mark.asyncio
    async def test_kb_semantic(self, msg):
        with patch("routers.chat_intents.knowledge._kb_semantic", return_value="semantic"):
            from routers.chat_intents.knowledge import handle
            assert await handle(msg, msg.lower()) == "semantic"

    @pytest.mark.parametrize("msg", ["kb search cpu", "knowledge search error", "知识搜索 问题"])
    @pytest.mark.asyncio
    async def test_kb_search(self, msg):
        with patch("routers.chat_intents.knowledge._kb_search", return_value="search"):
            from routers.chat_intents.knowledge import handle
            assert await handle(msg, msg.lower()) == "search"

    @pytest.mark.parametrize("msg", ["kb index", "kb init", "create index"])
    @pytest.mark.asyncio
    async def test_kb_index(self, msg):
        with patch("routers.chat_intents.knowledge._kb_index", return_value="indexed"):
            from routers.chat_intents.knowledge import handle
            assert await handle(msg, msg.lower()) == "indexed"

    @pytest.mark.parametrize("msg", ["learn incident", "学习故障", "learn from"])
    @pytest.mark.asyncio
    async def test_learn_incident(self, msg):
        from routers.chat_intents.knowledge import handle
        result = await handle(msg, msg.lower())
        assert "POST" in result or "学习" in result

    @pytest.mark.parametrize("msg", ["feedback abc123 good", "反馈"])
    @pytest.mark.asyncio
    async def test_feedback(self, msg):
        with patch("routers.chat_intents.knowledge._feedback", return_value="fb"):
            from routers.chat_intents.knowledge import handle
            assert await handle(msg, msg.lower()) == "fb"


def _kb_module(**overrides):
    mod = MagicMock()
    for k, v in overrides.items():
        setattr(mod, k, v)
    return mod


class TestKnowledgeHelpers:

    def test_kb_stats_success(self):
        mock_store = MagicMock()
        mock_store.get_stats.return_value = {
            "total_patterns": 50, "avg_confidence": 0.85,
            "by_category": {"compute": 20, "database": 30},
            "by_service": {"ec2": 15, "rds": 35},
        }
        mod = _kb_module(get_knowledge_store=MagicMock(return_value=mock_store))
        with patch.dict("sys.modules", {"src.knowledge_search": mod}):
            from routers.chat_intents.knowledge import _kb_stats
            result = _kb_stats()
            assert "知识库统计" in result
            assert "50" in result

    def test_kb_search_no_query(self):
        from routers.chat_intents.knowledge import _kb_search
        result = _kb_search("kb search")
        assert result is not None

    def test_kb_search_no_results(self):
        mock_store = MagicMock()
        mock_store.search_patterns.return_value = []
        mod = _kb_module(get_knowledge_store=MagicMock(return_value=mock_store))
        with patch.dict("sys.modules", {"src.knowledge_search": mod}):
            from routers.chat_intents.knowledge import _kb_search
            result = _kb_search("kb search nonexistent term")
            assert "未找到" in result

    def test_kb_search_with_results(self):
        mock_pattern = MagicMock()
        mock_pattern.title = "High CPU"
        mock_pattern.pattern_id = "pat-1"
        mock_pattern.category = "compute"
        mock_pattern.service = "ec2"
        mock_pattern.confidence = 0.9
        mock_pattern.symptoms = ["high cpu", "slow"]
        mock_pattern.remediation = "Scale up or check processes"

        mock_store = MagicMock()
        mock_store.search_patterns.return_value = [mock_pattern]
        mod = _kb_module(get_knowledge_store=MagicMock(return_value=mock_store))
        with patch.dict("sys.modules", {"src.knowledge_search": mod}):
            from routers.chat_intents.knowledge import _kb_search
            result = _kb_search("kb search high cpu")
            assert "知识搜索结果" in result
            assert "High CPU" in result

    def test_kb_semantic_no_query(self):
        from routers.chat_intents.knowledge import _kb_semantic
        result = _kb_semantic("kb semantic")
        assert "用法" in result

    def test_kb_semantic_not_initialized(self):
        mock_search = MagicMock()
        mock_search._initialized = False
        mod = _kb_module(get_vector_search=MagicMock(return_value=mock_search))
        with patch.dict("sys.modules", {"src.vector_search": mod}):
            from routers.chat_intents.knowledge import _kb_semantic
            result = _kb_semantic("kb semantic high cpu")
            assert "未初始化" in result

    def test_kb_semantic_no_results(self):
        mock_search = MagicMock()
        mock_search._initialized = True
        mock_search.hybrid_search.return_value = []
        mod = _kb_module(get_vector_search=MagicMock(return_value=mock_search))
        with patch.dict("sys.modules", {"src.vector_search": mod}):
            from routers.chat_intents.knowledge import _kb_semantic
            result = _kb_semantic("kb semantic obscure query")
            assert "未找到" in result

    def test_kb_semantic_with_results(self):
        mock_search = MagicMock()
        mock_search._initialized = True
        mock_search.hybrid_search.return_value = [
            {"title": "CPU Issue", "type": "pattern", "service": "ec2",
             "score": 0.95, "description": "CPU overload pattern"},
        ]
        mod = _kb_module(get_vector_search=MagicMock(return_value=mock_search))
        with patch.dict("sys.modules", {"src.vector_search": mod}):
            from routers.chat_intents.knowledge import _kb_semantic
            result = _kb_semantic("semantic search cpu overload")
            assert "语义搜索结果" in result
            assert "CPU Issue" in result

    def test_kb_index_success(self):
        mock_search = MagicMock()
        mock_search.create_index.return_value = True
        mod = _kb_module(get_vector_search=MagicMock(return_value=mock_search))
        with patch.dict("sys.modules", {"src.vector_search": mod}):
            from routers.chat_intents.knowledge import _kb_index
            result = _kb_index()
            assert "创建成功" in result

    def test_kb_index_failure(self):
        mock_search = MagicMock()
        mock_search.create_index.return_value = False
        mod = _kb_module(get_vector_search=MagicMock(return_value=mock_search))
        with patch.dict("sys.modules", {"src.vector_search": mod}):
            from routers.chat_intents.knowledge import _kb_index
            result = _kb_index()
            assert "失败" in result

    def test_feedback_no_pattern(self):
        from routers.chat_intents.knowledge import _feedback
        result = _feedback("feedback", "feedback")
        assert "用法" in result

    def test_feedback_good(self):
        mock_handler = MagicMock()
        mock_handler.submit_feedback.return_value = True
        mod = _kb_module(get_feedback_handler=MagicMock(return_value=mock_handler))
        with patch.dict("sys.modules", {"src.knowledge_search": mod}):
            from routers.chat_intents.knowledge import _feedback
            result = _feedback("feedback abc123 good", "feedback abc123 good")
            assert "已提交" in result
            assert "有帮助" in result

    def test_feedback_bad(self):
        mock_handler = MagicMock()
        mock_handler.submit_feedback.return_value = True
        mod = _kb_module(get_feedback_handler=MagicMock(return_value=mock_handler))
        with patch.dict("sys.modules", {"src.knowledge_search": mod}):
            from routers.chat_intents.knowledge import _feedback
            result = _feedback("feedback abc123 bad", "feedback abc123 bad")
            assert "已提交" in result
            assert "无帮助" in result

    def test_feedback_pattern_not_found(self):
        mock_handler = MagicMock()
        mock_handler.submit_feedback.return_value = False
        mod = _kb_module(get_feedback_handler=MagicMock(return_value=mock_handler))
        with patch.dict("sys.modules", {"src.knowledge_search": mod}):
            from routers.chat_intents.knowledge import _feedback
            result = _feedback("feedback abc123 good", "feedback abc123 good")
            assert "不存在" in result
