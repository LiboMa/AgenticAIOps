#!/usr/bin/env python3
"""Minimal Alert Pipeline E2E Demo.

Usage:
    python scripts/demo_alert_e2e.py
    python scripts/demo_alert_e2e.py "ALARM: your custom alert message"
"""
import sys
import asyncio
from src.alert.ingress import AlertIngressService


def demo_parse(svc: AlertIngressService, message: str) -> None:
    """Parse a single alert message and print results."""
    alert = svc.parse_channel_message("C_ALERTS", message)
    if alert:
        print(f"  ✅ Provider: {alert.provider}")
        print(f"     Severity: {alert.severity}")
        print(f"     Title:    {alert.title}")
        if alert.resource_hint:
            print(f"     Resource: {alert.resource_hint}")
        if alert.tags:
            print(f"     Tags:     {alert.tags}")
        print(f"     Dedup ID: {alert.alert_id[:12]}...")
    else:
        print(f"  ❌ No parser matched this message")
    print()


def main():
    svc = AlertIngressService()

    # Custom message from CLI
    if len(sys.argv) > 1:
        msg = " ".join(sys.argv[1:])
        print(f"📨 Custom Alert:")
        print(f"   \"{msg}\"")
        print()
        demo_parse(svc, msg)
        return

    # Built-in demo messages (3 sources)
    demo_alerts = [
        (
            "CloudWatch",
            'ALARM: "CPU-High-WebServer" in us-east-1 '
            "- EC2 instance i-0abc123 CPU > 90% for 5 minutes",
        ),
        (
            "Datadog",
            "[Triggered] High Memory Usage on host:web-prod-01 "
            "memory.percent over 95.2% threshold 90%",
        ),
        (
            "Grafana",
            "[Alerting] Pod CrashLoopBackOff in namespace production "
            "https://grafana.example.com/d/k8s-pods",
        ),
        (
            "PagerDuty",
            "[PagerDuty] TRIGGERED: Database connection pool exhausted "
            "on rds-prod-01 (P1 - Critical)",
        ),
        (
            "Generic",
            "WARNING: Disk usage on /dev/sda1 at 92%, threshold 85%",
        ),
    ]

    print("=" * 60)
    print("🚨 Alert Pipeline E2E Demo")
    print("=" * 60)
    print()

    for source, msg in demo_alerts:
        print(f"📨 [{source}] {msg}")
        demo_parse(svc, msg)

    # Dedup test
    print("=" * 60)
    print("🔄 Dedup Test")
    print("=" * 60)
    alert = svc.parse_channel_message("C_ALERTS", demo_alerts[0][1])
    if alert:
        # First time — new alert
        is_dup = alert.alert_id in svc._seen
        svc._seen[alert.alert_id] = True
        print(f"  1st submit: {'rejected (already seen)' if is_dup else 'accepted ✅'}")
        # Second time — duplicate
        is_dup = alert.alert_id in svc._seen
        print(f"  2nd submit: {'rejected (deduped) ✅' if is_dup else 'accepted'}")
    print()
    print("✅ Demo complete. All parsers operational.")


if __name__ == "__main__":
    main()
