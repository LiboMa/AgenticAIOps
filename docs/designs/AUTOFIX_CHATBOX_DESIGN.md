# 设计方案: Auto-Fix + Chatbox File Attachment 优化

**版本:** v1.0 | **日期:** 2026-02-16 | **作者:** Architect

---

## Task 1: Issue 自动修复 (Auto-Fix)

### 现状
- `incident_orchestrator.handle_incident(auto_execute=False)` — 默认不自动执行
- L0/L1 SOP 的 Safety 检查已通过 (`AUTO`/`NOTIFY` mode)
- `_execute_sop()` 方法存在但只在 `auto_execute=True` 时调用
- SOP steps 是文字描述，`sop_system.py` 的 `start_execution()` 只记录状态

### 改动

**S1: 启用 L0/L1 自动执行 (后端)**

```python
# incident_orchestrator.py — handle_incident() 改动
# 当 SOP 是 L0/L1 且 safety passed → 自动执行，不需要 auto_execute=True

if safety_result.passed and not dry_run:
    risk = safety._classify_risk(best_sop['sop_id'])
    if risk in (RiskLevel.L0, RiskLevel.L1):
        # L0/L1: 自动执行
        exec_result = self._execute_sop(...)
    elif risk == RiskLevel.L2:
        # L2: 需手动确认 (已有 Diagnose & Fix UI)
        incident.status = IncidentStatus.WAITING_APPROVAL
    else:
        # L3: 需审批
        approval = safety.request_approval(...)
```

**S2: SOP 真实执行逻辑 (后端)**

给 top 5 常见 SOP 添加真实 AWS 操作:

```python
# sop_system.py — SOPExecutor 扩展

SOP_ACTIONS = {
    "sop-ec2-high-cpu": [
        {"action": "describe_instances", "type": "L0"},      # 查看实例状态
        {"action": "get_metric_data", "type": "L0"},          # 确认 CPU 指标
        {"action": "create_auto_scaling_policy", "type": "L1"}, # 扩容
    ],
    "sop-ec2-unreachable": [
        {"action": "describe_instance_status", "type": "L0"},
        {"action": "reboot_instances", "type": "L1"},         # 重启
    ],
    "sop-ec2-disk-full": [
        {"action": "describe_volumes", "type": "L0"},
        {"action": "modify_volume", "type": "L2"},            # 扩容 EBS
    ],
    "sop-elb-5xx-spike": [
        {"action": "describe_target_health", "type": "L0"},
        {"action": "register_targets", "type": "L1"},         # 注册新实例
    ],
    "sop-rds-connection-limit": [
        {"action": "describe_db_instances", "type": "L0"},
        {"action": "modify_db_instance", "type": "L2"},       # 调参数
    ],
}
```

**S3: 执行结果 → Feedback 闭环**

已有 `_learn_from_incident()` (commit `89f7dc2`)。自动执行后调用即可。

---

## Task 2: Chatbox File Attachment 优化

### 现状
- `FileDropZone.jsx`: UI-only，文件 staged 但标注 "upload coming in P1"
- `ChatPanelPD.jsx`: 读取文件内容 (`reader.readAsText`)，截取前 10,000 字符拼到 message 里发送
- 问题:
  1. 只支持文本文件 (`readAsText`)，二进制文件 (图片/PDF) 无法处理
  2. 10KB 截断 — 大日志文件丢失关键内容
  3. FileDropZone 显示 "upload coming in P1" — 用户以为不能用
  4. 无后端文件上传端点

### 改动

**S4: 后端文件上传 API**

```python
# api_server.py 新增
from fastapi import UploadFile, File

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """上传文件，返回 file_id + 解析摘要"""
    content = await file.read()
    file_id = hashlib.sha256(content).hexdigest()[:12]
    
    # 保存到 data/uploads/
    upload_dir = Path("data/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    filepath = upload_dir / f"{file_id}_{file.filename}"
    filepath.write_bytes(content)
    
    # 解析内容摘要
    summary = _parse_file_summary(filepath, file.content_type)
    
    return {
        "file_id": file_id,
        "filename": file.filename,
        "size": len(content),
        "content_type": file.content_type,
        "summary": summary,  # 前 50 行 or 图片描述
    }

def _parse_file_summary(filepath, content_type):
    """解析文件前 50 行 (文本) 或元数据 (二进制)"""
    if content_type and content_type.startswith("text"):
        lines = filepath.read_text(errors='replace').split('\n')[:50]
        return '\n'.join(lines)
    elif content_type and content_type.startswith("image"):
        return f"[Image: {filepath.name}]"
    else:
        return f"[Binary file: {filepath.name}, {filepath.stat().st_size} bytes]"
```

**S5: 前端优化**

```
ChatPanelPD.jsx 改动:
1. 文件上传改为 FormData → POST /api/upload (不再 readAsText 全量拼接)
2. 支持二进制文件 (图片/PDF/日志)
3. 大文件分块: 文本 > 50KB 时只发摘要 + file_id，chat 引用 file_id
4. 上传进度条
5. 文件预览 (文本前 20 行 / 图片缩略图)

FileDropZone.jsx 改动:
1. 去掉 "upload coming in P1" 提示
2. 上传成功后显示 ✅ 状态
3. 支持 paste 图片 (Ctrl+V)
```

**S6: Chat 集成文件分析**

```python
# api_server.py — chat handler 改动
# 当 message 包含 file_id 时，从 data/uploads/ 读取完整内容分析
if 'file_id:' in message:
    file_content = _load_uploaded_file(file_id)
    # 传给 Bedrock Claude 做日志分析
```

---

## 预估

| 步骤 | 内容 | 工作量 |
|------|------|--------|
| S1 | L0/L1 自动执行开关 | 2h |
| S2 | Top 5 SOP 真实 AWS 操作 | 4h |
| S3 | 执行 → Feedback 闭环 | 1h |
| S4 | 后端 /api/upload | 2h |
| S5 | 前端文件上传优化 | 4h |
| S6 | Chat 文件分析集成 | 2h |
| **总计** | | **~2 天** |

## 优先级

1. **S1 + S2** — Auto-fix (Ma Ronnie 首要需求)
2. **S4 + S5** — File attachment 后端 + 前端
3. **S3 + S6** — 闭环 + 文件分析
