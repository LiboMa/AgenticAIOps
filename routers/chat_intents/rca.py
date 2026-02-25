"""RCA, SOP, incident, and safety intents."""

import re
import json
import traceback
from typing import Optional

from routers.deps import get_scanner, get_current_region, logger


async def handle(message: str, message_lower: str) -> Optional[str]:
    """Route RCA / SOP / incident / safety intents. Returns None if not matched."""

    # --- Incident Run (closed loop) ---
    if any(kw in message_lower for kw in ['incident run', '事件处理', 'incident handle', 'closed loop', '闭环']):
        return await _incident_run(message, message_lower)

    # --- Incident List ---
    if any(kw in message_lower for kw in ['incident list', '事件列表', 'incidents']):
        return _incident_list()

    # --- Incident Stats ---
    if any(kw in message_lower for kw in ['incident stats', '事件统计']):
        return _incident_stats()

    # --- RCA Deep ---
    if any(kw in message_lower for kw in ['rca deep', 'rca 深度', 'deep analyze', '深度分析']):
        return await _rca_deep(message, message_lower)

    # --- RCA Analyze ---
    if any(kw in message_lower for kw in ['rca analyze', 'rca 分析', 'diagnose', '诊断问题', 'root cause']):
        return _rca_analyze(message)

    # --- RCA Autofix ---
    if any(kw in message_lower for kw in ['rca autofix', 'rca 自动修复', 'auto diagnose']):
        return _rca_autofix(message)

    # --- RCA Feedback ---
    if any(kw in message_lower for kw in ['rca feedback', 'rca 反馈']):
        return _rca_feedback(message_lower)

    # --- RCA Stats ---
    if any(kw in message_lower for kw in ['rca stats', 'rca 统计', 'rca status']):
        return _rca_stats()

    # --- Safety Check / Dry Run ---
    if any(kw in message_lower for kw in ['safety check', '安全检查', 'sop check', 'dry run', 'dry-run']):
        return _safety_check(message)

    # --- Safety Stats ---
    if any(kw in message_lower for kw in ['safety stats', '安全统计', 'safety status']):
        return _safety_stats()

    # --- Approvals ---
    if any(kw in message_lower for kw in ['approvals', '审批列表', 'pending approvals']):
        return _pending_approvals()

    # --- Approve / Reject ---
    if any(kw in message_lower for kw in ['approve ', 'reject ']):
        return _approve_reject(message)

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
# Private helpers — Incident
# =========================================================================

async def _incident_run(message: str, message_lower: str) -> str:
    try:
        from src.detect_agent import get_detect_agent

        # Parse options
        dry_run = 'dry' in message_lower or '预览' in message_lower
        auto_exec = 'auto' in message_lower or '自动' in message_lower
        force_refresh = 'refresh' in message_lower or '刷新' in message_lower

        # Parse lookback (e.g., "incident run 30min")
        lb_match = re.search(r'(\d+)\s*min', message, re.IGNORECASE)
        lookback = int(lb_match.group(1)) if lb_match else 15

        match = re.search(r'(?:incident|事件|闭环)\s+(?:run|handle|处理)?\s*(ec2|rds|lambda)?', message, re.IGNORECASE)
        service_filter = [match.group(1).lower()] if match and match.group(1) else None

        # Use DetectAgent: collect once, reuse cached data
        detect = get_detect_agent(get_current_region())
        incident = await detect.trigger_incident(
            trigger_type="manual",
            services=service_filter,
            auto_execute=auto_exec,
            dry_run=dry_run,
            lookback_minutes=lookback,
        )

        return incident.to_markdown()
    except Exception as e:
        return f"❌ 事件处理失败: {str(e)}\n```\n{traceback.format_exc()[:500]}\n```"


def _incident_list() -> str:
    try:
        from src.incident_orchestrator import get_orchestrator

        orchestrator = get_orchestrator(get_current_region())
        incidents = orchestrator.list_incidents(limit=10)

        if not incidents:
            return "📋 暂无事件记录。使用 `incident run` 启动闭环分析。"

        response = f"📋 **事件列表** ({len(incidents)})\n\n"
        response += "| ID | 触发 | 状态 | 耗时 | 时间 |\n|-----|------|------|------|------|\n"
        for inc in incidents:
            status_icon = '✅' if inc['status'] == 'completed' else '❌' if inc['status'] == 'failed' else '⏳'
            response += f"| `{inc['incident_id'][:12]}` | {inc['trigger_type']} | {status_icon} {inc['status']} | {inc['duration_ms']}ms | {inc['created_at'][:19]} |\n"
        return response
    except Exception as e:
        return f"❌ 获取事件列表失败: {str(e)}"


def _incident_stats() -> str:
    try:
        from src.incident_orchestrator import get_orchestrator

        orchestrator = get_orchestrator(get_current_region())
        stats = orchestrator.get_stats()

        target_icon = '✅' if stats['within_target'] else '⚠️'

        response = f"""📊 **闭环管道统计**

| 指标 | 值 |
|------|-----|
| 总事件数 | {stats['total_incidents']} |
| 平均耗时 | {stats['avg_duration_ms']}ms |
| 目标 | {target_icon} {stats['target_ms']}ms |
"""
        if stats['by_status']:
            response += "\n**状态分布:**\n"
            for status, count in stats['by_status'].items():
                response += f"- {status}: {count}\n"

        if stats['avg_stage_timings']:
            response += "\n**各阶段平均耗时:**\n\n"
            response += "| 阶段 | 耗时 |\n|------|------|\n"
            for stage, ms in stats['avg_stage_timings'].items():
                response += f"| {stage} | {ms}ms |\n"

        return response
    except Exception as e:
        return f"❌ 获取统计失败: {str(e)}"


# =========================================================================
# Private helpers — RCA
# =========================================================================

async def _rca_deep(message: str, message_lower: str) -> str:
    try:
        from src.event_correlator import get_correlator
        from src.rca_inference import get_rca_inference_engine
        from src.rca_sop_bridge import get_bridge

        # Parse optional service filter
        match = re.search(r'(?:rca deep|deep analyze|深度分析)\s*(.*)', message, re.IGNORECASE)
        service_filter = None
        if match and match.group(1).strip():
            svc = match.group(1).strip().lower()
            if svc in ['ec2', 'rds', 'lambda']:
                service_filter = [svc]

        # Step 1: Collect data
        correlator = get_correlator(get_current_region())
        event = await correlator.collect(services=service_filter, lookback_minutes=15)

        # Step 2: Claude inference
        engine = get_rca_inference_engine()
        rca_result = await engine.analyze(event)

        # Step 3: SOP suggestion
        bridge = get_bridge()
        sop_suggestions = bridge.match_sops(rca_result)

        # Build response
        from src.rca.models import Severity
        severity_icon = '🔴' if rca_result.severity == Severity.HIGH else '🟡' if rca_result.severity == Severity.MEDIUM else '🟢'

        # Build response
        response = f"""🔬 **深度 RCA 分析** (Region: {get_current_region()})

**采集数据:** {len(event.metrics)} 指标 | {len(event.alarms)} 告警 | {len(event.trail_events)} 事件 | 耗时 {event.duration_ms}ms

---

**根因:** {rca_result.root_cause}
**严重性:** {severity_icon} {rca_result.severity.value.upper()}
**置信度:** {rca_result.confidence:.0%}
**分析模型:** `{rca_result.pattern_id}`

### 📋 证据链
"""
        for e in rca_result.evidence:
            response += f"- {e}\n"

        if sop_suggestions:
            response += "\n### 🛠️ 推荐 SOP\n\n"
            response += "| SOP | 名称 | 匹配度 | 步骤 |\n|-----|------|--------|------|\n"
            for sop in sop_suggestions[:3]:
                response += f"| `{sop['sop_id']}` | {sop['name']} | {sop['match_confidence']:.0%} | {sop['steps']}步 |\n"
            response += "\n使用 `sop run <id>` 执行"

        if rca_result.remediation.suggestion:
            response += f"\n\n### 💡 建议\n{rca_result.remediation.suggestion}"

        return response
    except Exception as e:
        return f"❌ 深度 RCA 分析失败: {str(e)}\n```\n{traceback.format_exc()[:500]}\n```"


def _rca_analyze(message: str) -> str:
    try:
        from src.rca_sop_bridge import get_bridge

        bridge = get_bridge()

        # Extract symptoms from the message
        # e.g., "rca analyze high cpu memory leak"
        match = re.search(r'(?:rca analyze|diagnose|诊断问题|root cause)\s*(.*)', message, re.IGNORECASE)
        symptoms = []
        if match and match.group(1).strip():
            symptoms = match.group(1).strip().split()

        if not symptoms:
            return """🔍 **RCA 分析 + SOP 推荐**

用法: `rca analyze <症状描述>`

示例:
- `rca analyze high cpu memory leak`
- `rca analyze OOMKilled crash loop`
- `rca analyze rds connection timeout`
- `diagnose lambda timeout error`

这将执行根因分析并自动推荐相关 SOP。"""

        result = bridge.analyze_and_suggest(
            symptoms=symptoms,
            auto_execute=False,  # Don't auto-execute from chat
        )

        return result.to_markdown()
    except Exception as e:
        return f"❌ RCA 分析失败: {str(e)}"


def _rca_autofix(message: str) -> str:
    try:
        from src.rca_sop_bridge import get_bridge

        bridge = get_bridge()

        match = re.search(r'(?:rca autofix|rca 自动修复|auto diagnose)\s*(.*)', message, re.IGNORECASE)
        symptoms = match.group(1).strip().split() if match and match.group(1).strip() else []

        if not symptoms:
            return """⚡ **RCA 自动修复**

用法: `rca autofix <症状描述>`

示例: `rca autofix high cpu`

⚠️ 仅 LOW 严重性 + 高置信度 (≥80%) 会自动执行 SOP"""

        result = bridge.analyze_and_suggest(
            symptoms=symptoms,
            auto_execute=True,
        )

        return result.to_markdown()
    except Exception as e:
        return f"❌ RCA 自动修复失败: {str(e)}"


def _rca_feedback(message_lower: str) -> str:
    try:
        from src.rca_sop_bridge import get_bridge

        # Format: rca feedback <execution_id> <sop_id> <pattern_id> success/fail
        match = re.search(
            r'rca feedback\s+(\S+)\s+(\S+)\s+(\S+)\s+(success|fail|good|bad)',
            message_lower
        )
        if not match:
            return """📝 **RCA 执行反馈**

用法: `rca feedback <execution_id> <sop_id> <pattern_id> success/fail`

示例: `rca feedback exec123 sop-ec2-high-cpu oom-killed success`

这有助于系统学习哪些 SOP 能有效解决特定根因。"""

        bridge = get_bridge()
        success = match.group(4) in ['success', 'good']

        feedback = bridge.submit_feedback(
            execution_id=match.group(1),
            sop_id=match.group(2),
            rca_pattern_id=match.group(3),
            success=success,
            root_cause_confirmed=success,
        )

        emoji = "✅" if success else "❌"
        return f"""{emoji} **RCA 反馈已记录**

- 执行 ID: `{feedback.execution_id}`
- SOP: `{feedback.sop_id}`
- Pattern: `{feedback.rca_pattern_id}`
- 结果: {'成功 ✅' if success else '失败 ❌'}
- 根因确认: {'是' if success else '否'}

{'系统将在未来优先推荐此 SOP 处理类似问题。' if success else '系统将降低此 SOP 的推荐优先级。'}"""
    except Exception as e:
        return f"❌ 反馈提交失败: {str(e)}"


def _rca_stats() -> str:
    try:
        from src.rca_sop_bridge import get_bridge

        bridge = get_bridge()
        stats = bridge.get_feedback_stats()

        response = f"""📊 **RCA ↔ SOP 统计**

| 指标 | 值 |
|------|-----|
| 总反馈数 | {stats['total_feedbacks']} |
| 成功解决 | {stats['successful']} |
| 解决失败 | {stats['failed']} |
| 根因确认 | {stats['root_cause_confirmed']} |
| 成功率 | {stats['success_rate']:.0%} |
| 平均解决时间 | {stats['avg_resolution_seconds']:.0f}s |
"""
        if stats['learned_mappings']:
            response += "\n**🧠 已学习的 Pattern → SOP 映射:**\n\n"
            for pattern_id, sops in stats['learned_mappings'].items():
                for sop_id, count in sops.items():
                    response += f"- `{pattern_id}` → `{sop_id}` ({count}次成功)\n"

        return response
    except Exception as e:
        return f"❌ 获取统计失败: {str(e)}"


# =========================================================================
# Private helpers — Safety
# =========================================================================

def _safety_check(message: str) -> str:
    try:
        from src.sop_safety import get_safety_layer

        match = re.search(r'(?:safety check|安全检查|sop check|dry.run)\s*(\S*)', message, re.IGNORECASE)
        sop_id = match.group(1).strip() if match and match.group(1).strip() else None

        if not sop_id:
            return """🛡️ **安全检查 / Dry-Run**

用法: `safety check <sop_id>` 或 `dry run <sop_id>`

示例:
- `safety check sop-ec2-high-cpu`
- `dry run sop-rds-failover`
- `safety check sop-lambda-errors`

显示风险等级、执行模式、冷却状态。"""

        safety = get_safety_layer()
        check = safety.check(sop_id=sop_id, dry_run=True)
        return check.to_markdown()
    except Exception as e:
        return f"❌ 安全检查失败: {str(e)}"


def _safety_stats() -> str:
    try:
        from src.sop_safety import get_safety_layer

        safety = get_safety_layer()
        stats = safety.get_stats()

        return f"""🛡️ **安全层状态**

| 指标 | 值 |
|------|-----|
| 活跃冷却 | {stats['active_cooldowns']} |
| 状态快照 | {stats['snapshots_stored']} |
| 待审批 | {stats['pending_approvals']} |

**日执行次数:**
```
{json.dumps(stats['daily_execution_counts'], indent=2) if stats['daily_execution_counts'] else '(今日无执行)'}
```

**日执行上限:**

| 级别 | 上限 | 冷却期 |
|------|------|--------|
| L0 (只读) | {stats['daily_limits']['L0']} | 无 |
| L1 (低风险) | {stats['daily_limits']['L1']} | 5 分钟 |
| L2 (中风险) | {stats['daily_limits']['L2']} | 30 分钟 |
| L3 (高风险) | {stats['daily_limits']['L3']} | 1 小时 |
"""
    except Exception as e:
        return f"❌ 获取安全统计失败: {str(e)}"


def _pending_approvals() -> str:
    try:
        from src.sop_safety import get_safety_layer

        safety = get_safety_layer()
        pending = safety.get_pending_approvals()

        if not pending:
            return "✅ 无待审批的 SOP 执行请求"

        response = f"🔐 **待审批 ({len(pending)})**\n\n"
        for a in pending:
            response += f"- `{a['approval_id']}`: **{a['sop_id']}** ({a['risk_level']}) — 请求人: {a['requested_by']}, 过期: {a['expires_at']}\n"
        response += "\n使用 `approve <approval_id>` 或 `reject <approval_id>` 处理"
        return response
    except Exception as e:
        return f"❌ 获取审批列表失败: {str(e)}"


def _approve_reject(message: str) -> str:
    try:
        from src.sop_safety import get_safety_layer

        safety = get_safety_layer()

        match = re.search(r'(approve|reject)\s+(\S+)', message, re.IGNORECASE)
        if not match:
            return "用法: `approve <approval_id>` 或 `reject <approval_id>`"

        action = match.group(1).lower()
        approval_id = match.group(2)

        if action == "approve":
            result = safety.approve(approval_id, approved_by="chat_user")
        else:
            result = safety.reject(approval_id, rejected_by="chat_user")

        if not result:
            return f"❌ 未找到审批请求: {approval_id}"

        status = "✅ 已批准" if result.approved else "❌ 已拒绝"
        return f"{status}: `{result.sop_id}` ({result.risk_level.value})"
    except Exception as e:
        return f"❌ 审批处理失败: {str(e)}"


# =========================================================================
# Private helpers — SOP
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
