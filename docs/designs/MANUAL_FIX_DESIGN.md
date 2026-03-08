# 设计方案: L2 手动 Fix 流程

**版本:** v1.0 | **日期:** 2026-02-14 | **作者:** Architect

---

## 背景

Ma Ronnie 要求：Low/Medium 级别 Issue 完成 RCA 报告后，支持手动确认 Fix。
当前系统对 L2 (Medium) 返回 `CONFIRM` 状态，但 WebUI 没有确认入口。

## 目标

```
Issue 列表 → 查看 RCA 报告 → 选择 SOP → 确认执行 → 结果反馈 → 闭环学习
```

## 实施步骤

### S1: 后端 REST API (Developer)

新增 3 个端点到 `api_server.py`:

```python
# 1. 单个 Incident 详情 (含 RCA + SOP + safety)
@app.get("/api/incident/{incident_id}")
async def get_incident_detail(incident_id: str):
    """返回完整 incident: RCA 结果 + 匹配 SOP + safety 状态"""
    orchestrator = get_orchestrator()
    incident = orchestrator.get_incident(incident_id)
    return {
        "incident": incident.to_dict(),
        "rca_result": incident.rca_result,
        "matched_sops": incident.matched_sops,
        "safety_check": incident.safety_result,
        "execution_status": incident.execution_status,
    }

# 2. 审批/确认执行 (REST 化现有 chat 命令)
@app.post("/api/incident/{incident_id}/approve")
async def approve_incident_fix(incident_id: str, body: ApproveRequest):
    """人工审阅 RCA 后确认执行 SOP"""
    safety = get_safety_layer()
    result = safety.approve(body.approval_id, approved_by=body.approved_by or "webui_user")
    if result and result.approved:
        # 触发 SOP 执行
        orchestrator = get_orchestrator()
        exec_result = orchestrator.execute_approved_sop(
            incident_id=incident_id,
            approval=result,
        )
        return {"status": "executing", "execution": exec_result}
    return {"status": "failed", "message": "Approval not found or already processed"}

# 3. SOP 执行步骤追踪
@app.post("/api/sop/execute/{execution_id}/step")
async def complete_sop_step(execution_id: str, body: StepCompleteRequest):
    """标记 SOP 步骤完成 + 记录结果"""
    executor = get_sop_executor()
    success = executor.complete_step(execution_id, {
        "step_index": body.step_index,
        "result": body.result,  # "success" | "failed"
        "notes": body.notes,
    })
    execution = executor.get_execution(execution_id)
    # 如果全部步骤完成，触发 feedback 闭环
    if execution and execution.status == "completed":
        orchestrator = get_orchestrator()
        orchestrator.record_fix_result(
            incident_id=body.incident_id,
            execution_id=execution_id,
            success=execution.success,
        )
    return {"execution": execution.__dict__ if execution else None}
```

**Orchestrator 新增方法:**

```python
# incident_orchestrator.py
async def execute_approved_sop(self, incident_id: str, approval) -> Dict:
    """审批通过后执行 SOP"""
    incident = self._incidents.get(incident_id)
    if not incident:
        return {"error": "Incident not found"}
    
    sop_id = approval.sop_id
    exec_result = self._execute_sop(
        sop_id=sop_id,
        rca_result=incident.rca_result,
        resource_ids=incident.resource_ids,
        safety=self._safety,
    )
    incident.execution_status = "executed"
    incident.execution_result = exec_result
    return exec_result

def record_fix_result(self, incident_id: str, execution_id: str, success: bool):
    """记录修复结果 + 触发 feedback 闭环"""
    incident = self._incidents.get(incident_id)
    if incident and incident.rca_result:
        self._auto_feedback(incident, incident.rca_result, incident.matched_sops)
```

### S2: 前端 UI (Developer)

在 `IssueCenterPD.jsx` 的 Issue 详情弹窗中:

1. 增加 "RCA Report" Tab — 显示根因、置信度、推荐 SOP
2. 增加 "Apply Fix" 按钮 — 调用 `/api/incident/{id}/approve`
3. 增加 SOP 步骤 Checklist — 每步 ✅/❌ + 备注
4. 增加执行结果状态 — 成功/失败/进行中

### S3: Feedback 闭环

已有 `_learn_from_incident()` (commit `89f7dc2`)。手动 Fix 完成后自动调用，无需新代码。

## 数据模型

```python
class ApproveRequest(BaseModel):
    approval_id: str
    approved_by: str = "webui_user"
    notes: str = ""

class StepCompleteRequest(BaseModel):
    incident_id: str
    step_index: int
    result: str  # "success" | "failed"
    notes: str = ""
```

## 预估

| 步骤 | 工作量 | 改动文件 |
|------|--------|----------|
| S1 后端 | 0.5 天 | api_server.py, incident_orchestrator.py |
| S2 前端 | 1 天 | IssueCenterPD.jsx |
| S3 测试 | 0.5 天 | test_manual_fix.py |
| **总计** | **2 天** | |
