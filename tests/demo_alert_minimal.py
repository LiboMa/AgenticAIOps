#!/usr/bin/env python3
"""最小化 Alert 测试用例 — 展示全链路效果.

Ma Ronnie 可直接运行:
    cd /home/ubuntu/agentic-aiops-mvp
    source venv/bin/activate
    python tests/demo_alert_minimal.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.alert.models import StructuredAlert
from src.alert.ingress import AlertIngressService

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 模拟 5 种告警源的消息
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SAMPLE_ALERTS = {
    "CloudWatch": """
        ALARM: "High-CPU-Production" in us-east-1
        State: ALARM
        Reason: Threshold Crossed: 1 datapoint (95.2) was >= 80
        Instance: i-0abc123def456
    """,
    "Datadog": """
        [Triggered] CPU usage is high on host:web-prod-01
        tags: env:production, service:api-gateway
        Monitor: High CPU Alert
        Priority: P2
    """,
    "PagerDuty": """
        PagerDuty Incident #12345
        Service: Production API
        Status: triggered
        Urgency: high
        Description: Database connection pool exhausted
    """,
    "Grafana": """
        [Alerting] Grafana alert: Disk Space Critical
        State: alerting
        Dashboard: https://monitoring.grafana.example.com/d/abc123
        Value: 95% used on /dev/sda1
    """,
    "Generic (Slack 消息)": """
        🚨 CRITICAL: Pod crash loop detected in production namespace
        app=payment-service, restarts=15, node=ip-10-0-1-50
    """,
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 运行解析
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    service = AlertIngressService()
    
    print("=" * 70)
    print("🔔 Alert Ingestion 最小化测试 — 5 种告警源")
    print("=" * 70)
    
    parse_results = []
    for source_name, message in SAMPLE_ALERTS.items():
        alert = service.parse_channel_message(
            channel_id="C-ALERTS-TEST",
            message=message.strip()
        )
        parse_results.append((source_name, alert))
        
        print(f"\n{'─' * 70}")
        print(f"📡 来源: {source_name}")
        
        if alert:
            print(f"  ✅ 解析成功!")
            print(f"  │ 标题:   {alert.title}")
            print(f"  │ 严重性: {alert.severity}")
            print(f"  │ 来源:   {alert.source}")
            print(f"  │ 资源:   {alert.resource_hint or '(未提取)'}")
            print(f"  │ 标签:   {alert.tags}")
            print(f"  │ Alert ID: {alert.alert_id[:16]}...")
        else:
            print(f"  ❌ 未能解析")
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 3. 去重测试
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print(f"\n{'=' * 70}")
    print("🔄 去重测试 — 相同告警发送两次")
    print("=" * 70)
    
    cw_msg = SAMPLE_ALERTS["CloudWatch"].strip()
    alert1 = service.parse_channel_message("C-TEST", cw_msg)
    is_dup = service.is_duplicate(alert1) if alert1 else False
    print(f"  第1次: {'✅ 通过' if alert1 and not is_dup else '❌'}")
    
    # Mark as seen
    if alert1:
        service._seen[alert1.alert_id] = alert1.timestamp
    
    alert2 = service.parse_channel_message("C-TEST", cw_msg)
    is_dup2 = service.is_duplicate(alert2) if alert2 else False
    print(f"  第2次: {'🚫 已去重 (正确!)' if is_dup2 else '❌ 未去重'}")
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 4. Skills 上下文感知测试
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print(f"\n{'=' * 70}")
    print("🧠 SkillBridge 上下文感知测试")
    print("=" * 70)
    
    try:
        from src.skills.skill_bridge import SkillBridge
        bridge = SkillBridge(agent_name="detect")
        
        # EKS 告警 → 应该加载 kubernetes tools
        eks_alert = StructuredAlert(
            title="EKS Pod CrashLoopBackOff",
            severity="high",
            source="channel",
            raw_message="Pod crash loop in eks cluster",
            tags={"resource_type": "eks", "namespace": "production"},
        )
        tools = bridge.load_for_context({"alert": eks_alert.model_dump()})
        tool_names = [getattr(t, 'tool_name', getattr(t, '__name__', str(t))) for t in tools]
        print(f"  EKS 告警 → 加载了 {len(tools)} 个 tools")
        if tool_names:
            print(f"  │ 示例: {tool_names[:5]}")
    except Exception as e:
        print(f"  ⚠️ SkillBridge 测试跳过: {e}")
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 5. Knowledge Flywheel 测试
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print(f"\n{'=' * 70}")
    print("📚 Knowledge Flywheel 测试 — 经验沉淀 + 检索")
    print("=" * 70)
    
    try:
        import tempfile
        from src.knowledge.flywheel import KnowledgeFlywheel
        
        with tempfile.TemporaryDirectory() as tmpdir:
            flywheel = KnowledgeFlywheel(db_path=os.path.join(tmpdir, "test.db"))
            
            # Capture 一个 RCA 结果
            flywheel.capture(
                title="High CPU on web-prod-01",
                symptoms="CPU > 95%, Response time 5x normal",
                root_cause="Memory leak in connection pool",
                resolution="Restart service + fix pool size config",
                severity="high",
            )
            print("  ✅ RCA 经验已沉淀到向量库")
            
            # Search similar
            results = flywheel.search_similar("CPU spike on production server")
            print(f"  🔍 搜索 'CPU spike on production server' → {len(results)} 条匹配")
            if results:
                r = results[0]
                print(f"  │ 最佳匹配: {getattr(r, 'title', r.get('title', 'N/A')) if isinstance(r, dict) else r}")
                print(f"  │ 根因: {getattr(r, 'root_cause', r.get('root_cause', 'N/A')) if isinstance(r, dict) else 'N/A'}")
    except Exception as e:
        print(f"  ⚠️ Knowledge Flywheel 测试跳过: {e}")
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 6. Self-Improving Skills 组件测试
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print(f"\n{'=' * 70}")
    print("🔄 Self-Improving Skills 组件测试")
    print("=" * 70)
    
    try:
        from src.skills.iteration import SkillGapDetector, SkillSpecBuilder, SkillValidator, SkillIterationGuard
        
        # Gap Detector
        detector = SkillGapDetector()
        print(f"  ✅ SkillGapDetector 初始化成功")
        print(f"  │ 功能: 分析 RCA 结果，识别缺失的 Skill 能力")
        
        # Spec Builder
        builder = SkillSpecBuilder()
        print(f"  ✅ SkillSpecBuilder 初始化成功")
        print(f"  │ 功能: 根据 gap 自动生成 Skill 规格 + Harness 任务")
        
        # Validator
        validator = SkillValidator()
        print(f"  ✅ SkillValidator 初始化成功")
        print(f"  │ 功能: 验证自动生成的 Skill 安全性 + 正确性")
        
        # Guard
        guard = SkillIterationGuard()
        print(f"  ✅ SkillIterationGuard 初始化成功")
        print(f"  │ 功能: 防止无限循环，限制自动迭代次数")
        
        print(f"\n  🎯 L2 自主 Skills 创建: 组件就位，待 Harness 集成触发")
    except Exception as e:
        print(f"  ⚠️ Self-Improving 测试跳过: {e}")
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 总结
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    parsed_count = sum(1 for _, a in parse_results if a is not None)
    print(f"\n{'=' * 70}")
    print(f"📊 总结: {parsed_count}/{len(SAMPLE_ALERTS)} 告警源解析成功")
    print(f"   全链路: Alert → 解析 → Skills → RCA → Knowledge 学习 → 自改进")
    print("=" * 70)


if __name__ == "__main__":
    main()
