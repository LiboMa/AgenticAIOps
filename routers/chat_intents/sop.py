"""SOP intents: list, show, suggest, run."""

import re
from typing import Optional

from routers.deps import logger


async def handle(message: str, message_lower: str) -> Optional[str]:
    """Route SOP intents. Returns None if not matched."""

    # --- SOP List ---
    if any(kw in message_lower for kw in ['sop list', 'sop 列表', 'list sop']):
        return _sop_list()

    # --- SOP Show ---
    if any(kw in message_lower for kw in ['sop show', 'sop 详情', 'show sop']):
        return _sop_show(message_lower)

    # --- SOP Suggest ---
    if any(kw in message_lower for kw in ['sop suggest', 'sop 推荐', 'suggest sop']):
        return _sop_suggest(message)

    # --- SOP Run ---
    if any(kw in message_lower for kw in ['sop run', 'sop 执行', 'run sop', 'execute sop']):
        return _sop_run(message_lower)

    return None


# =========================================================================
# Private helpers
# =========================================================================

def _sop_list() -> str:
    try:
        from src.sop_system import get_sop_store
        store = get_sop_store()

        # Parse optional filters
        service_filter = None
        category_filter = None

        sops = store.list_sops(service=service_filter, category=category_filter)

        if not sops:
            return "📋 没有可用的 SOP"

        response = f"""📋 **SOP 列表** ({len(sops)} 个)

| ID | 名称 | 服务 | 分类 | 严重性 |
|-----|------|------|------|--------|
"""
        for sop in sops:
            response += f"| {sop.sop_id} | {sop.name} | {sop.service} | {sop.category} | {sop.severity} |\n"

        response += "\n使用 `sop show <id>` 查看详情"
        return response
    except Exception as e:
        return f"❌ 获取 SOP 列表失败: {str(e)}"


def _sop_show(message_lower: str) -> str:
    try:
        match = re.search(r'(?:sop show|show sop)\s+(\S+)', message_lower)
        if not match:
            return """**查看 SOP 详情**

用法: `sop show <sop_id>`

示例: `sop show sop-ec2-high-cpu`"""

        sop_id = match.group(1)

        from src.sop_system import get_sop_store
        store = get_sop_store()
        sop = store.get_sop(sop_id)

        if not sop:
            return f"❌ SOP '{sop_id}' 不存在"

        response = f"""📋 **SOP: {sop.name}**

**ID:** {sop.sop_id}
**描述:** {sop.description}
**服务:** {sop.service}
**分类:** {sop.category}
**严重性:** {sop.severity}
**触发类型:** {sop.trigger_type}

**步骤:**
"""
        for i, step in enumerate(sop.steps, 1):
            step_obj = step if hasattr(step, 'name') else type('Step', (), step)()
            name = step.name if hasattr(step, 'name') else step.get('name', '')
            desc = step.description if hasattr(step, 'description') else step.get('description', '')
            response += f"{i}. **{name}** - {desc}\n"

        response += f"\n**标签:** {', '.join(sop.tags)}"
        return response
    except Exception as e:
        return f"❌ 获取 SOP 详情失败: {str(e)}"


def _sop_suggest(message: str) -> str:
    try:
        # Format: sop suggest <service> <keywords>
        match = re.search(r'suggest\s+(\w+)\s*(.*)', message, re.IGNORECASE)
        if not match:
            return """**推荐 SOP**

用法: `sop suggest <服务> <问题关键词>`

示例:
- `sop suggest ec2 high cpu`
- `sop suggest rds failover`
- `sop suggest lambda errors`"""

        service = match.group(1).lower()
        keywords = match.group(2).strip().split() if match.group(2) else []

        from src.sop_system import get_sop_store
        store = get_sop_store()

        suggested = store.suggest_sops(service, keywords)

        if not suggested:
            return f"🔍 没有找到与 '{service} {' '.join(keywords)}' 相关的 SOP"

        response = f"""🔍 **推荐 SOP** (服务: {service})

"""
        for sop in suggested:
            est_time = sum(s.estimated_minutes if hasattr(s, 'estimated_minutes') else 5 for s in sop.steps)
            response += f"**{sop.name}** (`{sop.sop_id}`)\n- {sop.description}\n- 步骤数: {len(sop.steps)} | 预计时间: {est_time}分钟\n\n"
        return response
    except Exception as e:
        return f"❌ SOP 推荐失败: {str(e)}"


def _sop_run(message_lower: str) -> str:
    try:
        match = re.search(r'(?:sop run|run sop|execute sop)\s+(\S+)', message_lower)
        if not match:
            return """**执行 SOP**

用法: `sop run <sop_id>`

示例: `sop run sop-ec2-high-cpu`

⚠️ 注意: 这将启动 SOP 执行流程，部分步骤可能需要人工确认"""

        sop_id = match.group(1)

        from src.sop_system import get_sop_store, get_sop_executor
        store = get_sop_store()
        executor = get_sop_executor()

        sop = store.get_sop(sop_id)
        if not sop:
            return f"❌ SOP '{sop_id}' 不存在"

        execution = executor.start_execution(sop_id, triggered_by="chat")

        if not execution:
            return f"❌ 启动 SOP 执行失败"

        response = f"""🚀 **SOP 执行已启动**

**SOP:** {sop.name}
**执行 ID:** {execution.execution_id}
**状态:** {execution.status}

**步骤预览:**
"""
        for i, step in enumerate(sop.steps, 1):
            name = step.name if hasattr(step, 'name') else step.get('name', '')
            step_type = step.step_type.value if hasattr(step, 'step_type') else step.get('step_type', 'manual')
            response += f"{i}. {name} ({step_type})\n"

        response += f"\n使用 `sop status {execution.execution_id}` 查看执行状态"
        return response
    except Exception as e:
        return f"❌ SOP 执行失败: {str(e)}"
