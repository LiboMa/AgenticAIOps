"""
Tests for routers/chat_intents/ui_actions.py — UI action detection (A2UI)

Coverage target: 100%.
Tests detect_ui_action() pattern matching and the handle() placeholder.
"""

import pytest
from routers.chat_intents.ui_actions import detect_ui_action, handle


class TestDetectUiAction:
    """Test UI action detection from message text."""

    # --- Positive cases: add/create patterns + widget types ---

    @pytest.mark.parametrize("msg,expected_type", [
        ("添加 EC2 widget", "stat-card"),
        ("add ec2 monitor", "stat-card"),
        ("创建 lambda table", "table"),
        ("create lambda dashboard", "table"),
        ("显示 CPU stats", "stat-card"),
        ("show cpu usage", "stat-card"),
        ("生成 memory card", "stat-card"),
        ("generate memory overview", "stat-card"),
    ])
    def test_add_patterns_with_widget_types(self, msg, expected_type):
        result = detect_ui_action(msg)
        assert result is not None
        assert result["action"] == "add_widget"
        assert result["widget"]["type"] == expected_type

    @pytest.mark.parametrize("msg,expected_type", [
        ("add alert panel", "alert-list"),
        ("创建告警 widget", "alert-list"),
        ("show service status", "service-status"),
        ("添加服务 monitor", "service-status"),
        ("create table view", "table"),
        ("添加表格", "table"),
        ("add card widget", "stat-card"),
        ("显示卡片", "stat-card"),
    ])
    def test_widget_type_detection(self, msg, expected_type):
        result = detect_ui_action(msg)
        assert result is not None
        assert result["widget"]["type"] == expected_type

    # --- Widget config ---

    def test_stat_card_has_value_zero(self):
        result = detect_ui_action("add ec2 monitor")
        assert result["widget"]["config"]["value"] == 0

    def test_table_has_value_none(self):
        result = detect_ui_action("add table view")
        assert result["widget"]["config"]["value"] is None

    def test_table_span_is_24(self):
        result = detect_ui_action("add table")
        assert result["widget"]["span"] == 24

    def test_non_table_span_is_8(self):
        result = detect_ui_action("add ec2 monitor")
        assert result["widget"]["span"] == 8

    def test_widget_config_has_title(self):
        result = detect_ui_action("add ec2 widget")
        assert "title" in result["widget"]["config"]
        assert "EC2" in result["widget"]["config"]["title"]

    def test_widget_config_has_icon(self):
        result = detect_ui_action("add ec2 widget")
        assert result["widget"]["config"]["icon"] == "cloud"

    def test_widget_config_has_color(self):
        result = detect_ui_action("add ec2 widget")
        assert result["widget"]["config"]["color"] == "#06AC38"

    # --- Negative cases ---

    def test_no_add_pattern_returns_none(self):
        """Messages without add/create/show patterns return None."""
        assert detect_ui_action("check ec2 status") is None

    def test_add_but_no_widget_type_returns_none(self):
        """Add pattern present but no recognized widget type → None."""
        assert detect_ui_action("add something unknown") is None

    def test_empty_message_returns_none(self):
        assert detect_ui_action("") is None

    def test_plain_question_returns_none(self):
        assert detect_ui_action("what is the CPU usage?") is None

    def test_widget_type_without_add_returns_none(self):
        """Widget type keyword present but no add/create pattern → None."""
        assert detect_ui_action("ec2 instance is down") is None

    def test_rca_message_returns_none(self):
        assert detect_ui_action("analyze rca for incident") is None

    # --- Case insensitivity ---

    def test_case_insensitive_add(self):
        result = detect_ui_action("ADD EC2 MONITOR")
        assert result is not None
        assert result["widget"]["type"] == "stat-card"

    def test_case_insensitive_create(self):
        result = detect_ui_action("CREATE Lambda Table")
        assert result is not None

    def test_mixed_case(self):
        result = detect_ui_action("Show CPU Stats")
        assert result is not None

    # --- Chinese patterns ---

    def test_chinese_add_with_chinese_widget(self):
        result = detect_ui_action("添加告警")
        assert result is not None
        assert result["widget"]["type"] == "alert-list"

    def test_chinese_create_with_service(self):
        result = detect_ui_action("创建服务监控")
        assert result is not None
        assert result["widget"]["type"] == "service-status"

    def test_chinese_show_with_table(self):
        result = detect_ui_action("显示表格")
        assert result is not None
        assert result["widget"]["type"] == "table"

    def test_chinese_generate_with_card(self):
        result = detect_ui_action("生成卡片")
        assert result is not None
        assert result["widget"]["type"] == "stat-card"


class TestHandle:
    """Test the handle() placeholder."""

    @pytest.mark.asyncio
    async def test_handle_always_returns_none(self):
        """handle() is a placeholder that always returns None."""
        result = await handle("add ec2", "add ec2")
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_returns_none_for_any_input(self):
        result = await handle("", "")
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_returns_none_for_ui_action_message(self):
        """Even with a valid UI action message, handle() returns None."""
        result = await handle("添加 EC2 widget", "添加 ec2 widget")
        assert result is None
