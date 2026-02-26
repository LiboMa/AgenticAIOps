"""Tests for routers/chat_intents/sop.py — keyword routing + helpers."""

import pytest
from unittest.mock import patch, MagicMock


class TestSOPHandle:

    @pytest.mark.asyncio
    async def test_no_match(self):
        from routers.chat_intents.sop import handle
        assert await handle("hello", "hello") is None

    @pytest.mark.parametrize("msg", ["sop list", "sop 列表", "list sop"])
    @pytest.mark.asyncio
    async def test_sop_list(self, msg):
        with patch("routers.chat_intents.sop._sop_list", return_value="list"):
            from routers.chat_intents.sop import handle
            assert await handle(msg, msg.lower()) == "list"

    @pytest.mark.parametrize("msg", ["sop show sop-1", "sop 详情 sop-1", "show sop sop-1"])
    @pytest.mark.asyncio
    async def test_sop_show(self, msg):
        with patch("routers.chat_intents.sop._sop_show", return_value="detail"):
            from routers.chat_intents.sop import handle
            assert await handle(msg, msg.lower()) == "detail"

    @pytest.mark.parametrize("msg", ["sop suggest ec2 cpu", "sop 推荐 ec2", "suggest sop ec2"])
    @pytest.mark.asyncio
    async def test_sop_suggest(self, msg):
        with patch("routers.chat_intents.sop._sop_suggest", return_value="suggest"):
            from routers.chat_intents.sop import handle
            assert await handle(msg, msg.lower()) == "suggest"

    @pytest.mark.parametrize("msg", ["sop run sop-1", "sop 执行 sop-1", "run sop sop-1", "execute sop sop-1"])
    @pytest.mark.asyncio
    async def test_sop_run(self, msg):
        with patch("routers.chat_intents.sop._sop_run", return_value="running"):
            from routers.chat_intents.sop import handle
            assert await handle(msg, msg.lower()) == "running"


def _sop_module(**overrides):
    mod = MagicMock()
    for k, v in overrides.items():
        setattr(mod, k, v)
    return mod


class TestSOPHelpers:

    def test_sop_list_empty(self):
        mock_store = MagicMock()
        mock_store.list_sops.return_value = []
        mod = _sop_module(get_sop_store=MagicMock(return_value=mock_store))
        with patch.dict("sys.modules", {"src.sop_system": mod}):
            from routers.chat_intents.sop import _sop_list
            result = _sop_list()
            assert "没有可用" in result

    def test_sop_list_with_data(self):
        mock_sop = MagicMock()
        mock_sop.sop_id = "sop-1"
        mock_sop.name = "EC2 High CPU"
        mock_sop.service = "ec2"
        mock_sop.category = "compute"
        mock_sop.severity = "high"

        mock_store = MagicMock()
        mock_store.list_sops.return_value = [mock_sop]
        mod = _sop_module(get_sop_store=MagicMock(return_value=mock_store))
        with patch.dict("sys.modules", {"src.sop_system": mod}):
            from routers.chat_intents.sop import _sop_list
            result = _sop_list()
            assert "SOP 列表" in result
            assert "sop-1" in result

    def test_sop_show_no_id(self):
        from routers.chat_intents.sop import _sop_show
        result = _sop_show("sop show")
        assert "用法" in result

    def test_sop_show_not_found(self):
        mock_store = MagicMock()
        mock_store.get_sop.return_value = None
        mod = _sop_module(get_sop_store=MagicMock(return_value=mock_store))
        with patch.dict("sys.modules", {"src.sop_system": mod}):
            from routers.chat_intents.sop import _sop_show
            result = _sop_show("sop show nonexistent")
            assert "不存在" in result

    def test_sop_show_success(self):
        mock_sop = MagicMock()
        mock_sop.sop_id = "sop-1"
        mock_sop.name = "EC2 High CPU"
        mock_sop.description = "Handle high CPU"
        mock_sop.service = "ec2"
        mock_sop.category = "compute"
        mock_sop.severity = "high"
        mock_sop.trigger_type = "alarm"
        mock_sop.steps = [MagicMock(name="Step1", description="Check CPU")]
        mock_sop.tags = ["cpu", "ec2"]

        mock_store = MagicMock()
        mock_store.get_sop.return_value = mock_sop
        mod = _sop_module(get_sop_store=MagicMock(return_value=mock_store))
        with patch.dict("sys.modules", {"src.sop_system": mod}):
            from routers.chat_intents.sop import _sop_show
            result = _sop_show("sop show sop-1")
            assert "sop-1" in result

    def test_sop_suggest_no_args(self):
        from routers.chat_intents.sop import _sop_suggest
        result = _sop_suggest("sop suggest")
        assert "用法" in result

    def test_sop_suggest_no_results(self):
        mock_store = MagicMock()
        mock_store.suggest_sops.return_value = []
        mod = _sop_module(get_sop_store=MagicMock(return_value=mock_store))
        with patch.dict("sys.modules", {"src.sop_system": mod}):
            from routers.chat_intents.sop import _sop_suggest
            result = _sop_suggest("sop suggest ec2 high cpu")
            assert "没有找到" in result

    def test_sop_suggest_success(self):
        mock_sop = MagicMock()
        mock_sop.name = "EC2 High CPU SOP"
        mock_sop.sop_id = "sop-ec2-cpu"
        mock_sop.description = "Handle EC2 high CPU"
        mock_sop.steps = [MagicMock(estimated_minutes=5)]

        mock_store = MagicMock()
        mock_store.suggest_sops.return_value = [mock_sop]
        mod = _sop_module(get_sop_store=MagicMock(return_value=mock_store))
        with patch.dict("sys.modules", {"src.sop_system": mod}):
            from routers.chat_intents.sop import _sop_suggest
            result = _sop_suggest("sop suggest ec2 high cpu")
            assert "推荐 SOP" in result

    def test_sop_run_no_id(self):
        from routers.chat_intents.sop import _sop_run
        result = _sop_run("sop run")
        assert "用法" in result

    def test_sop_run_not_found(self):
        mock_store = MagicMock()
        mock_store.get_sop.return_value = None
        mock_executor = MagicMock()
        mod = _sop_module(
            get_sop_store=MagicMock(return_value=mock_store),
            get_sop_executor=MagicMock(return_value=mock_executor),
        )
        with patch.dict("sys.modules", {"src.sop_system": mod}):
            from routers.chat_intents.sop import _sop_run
            result = _sop_run("sop run nonexistent")
            assert "不存在" in result

    def test_sop_run_success(self):
        mock_sop = MagicMock()
        mock_sop.name = "EC2 CPU SOP"
        mock_sop.steps = [MagicMock(name="step1", step_type=MagicMock(value="auto"))]

        mock_exec = MagicMock()
        mock_exec.execution_id = "exec-1"
        mock_exec.status = "running"

        mock_store = MagicMock()
        mock_store.get_sop.return_value = mock_sop
        mock_executor = MagicMock()
        mock_executor.start_execution.return_value = mock_exec

        mod = _sop_module(
            get_sop_store=MagicMock(return_value=mock_store),
            get_sop_executor=MagicMock(return_value=mock_executor),
        )
        with patch.dict("sys.modules", {"src.sop_system": mod}):
            from routers.chat_intents.sop import _sop_run
            result = _sop_run("sop run sop-1")
            assert "执行已启动" in result
            assert "exec-1" in result

    def test_sop_run_execution_failed(self):
        mock_sop = MagicMock()
        mock_store = MagicMock()
        mock_store.get_sop.return_value = mock_sop
        mock_executor = MagicMock()
        mock_executor.start_execution.return_value = None

        mod = _sop_module(
            get_sop_store=MagicMock(return_value=mock_store),
            get_sop_executor=MagicMock(return_value=mock_executor),
        )
        with patch.dict("sys.modules", {"src.sop_system": mod}):
            from routers.chat_intents.sop import _sop_run
            result = _sop_run("sop run sop-1")
            assert "启动 SOP 执行失败" in result
