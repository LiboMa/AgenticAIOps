"""Health-related intents: per-service health checks, anomaly detection, full health scan."""

from typing import Optional

from routers.deps import get_scanner, get_current_region, logger


def _get_ops():
    try:
        from src.aws_ops import get_aws_ops
        return get_aws_ops(get_current_region())
    except ImportError:
        return None


async def handle(message: str, message_lower: str) -> Optional[str]:
    """Route health / anomaly intents.  Returns None if not matched."""

    # --- EC2 Health ---
    if any(kw in message_lower for kw in ['ec2 health', 'ec2 健康', 'check ec2', '检查 ec2', 'ec2 status']):
        return _ec2_health()

    # --- RDS Health ---
    if any(kw in message_lower for kw in ['rds health', 'rds 健康', 'check rds', '检查 rds', 'database health', '数据库健康']):
        return _rds_health()

    # --- Lambda Health ---
    if any(kw in message_lower for kw in ['lambda health', 'lambda 健康', 'check lambda', '检查 lambda', 'function health']):
        return _lambda_health()

    # --- S3 Health ---
    if any(kw in message_lower for kw in ['s3 health', 's3 健康', 'check s3', '检查 s3', 'bucket health', 's3 security']):
        return _s3_health()

    # --- VPC Health ---
    if any(kw in message_lower for kw in ['vpc health', 'vpc 健康', 'check vpc']):
        return _vpc_health()

    # --- ELB Health ---
    if any(kw in message_lower for kw in ['elb health', 'lb health', 'load balancer health']):
        return _elb_health()

    # --- Route53 Health ---
    if any(kw in message_lower for kw in ['route53 health', 'dns health', 'route 53']):
        return _route53_health()

    # --- DynamoDB Health ---
    if any(kw in message_lower for kw in ['dynamodb health', 'ddb health', 'dynamo health']):
        return _dynamodb_health()

    # --- ECS Health ---
    if any(kw in message_lower for kw in ['ecs health', 'container health']):
        return _ecs_health()

    # --- ElastiCache Health ---
    if any(kw in message_lower for kw in ['elasticache health', 'cache health', 'redis health', 'memcached health']):
        return _elasticache_health()

    # --- Anomaly Detection ---
    if any(kw in message_lower for kw in ['anomaly', '异常', 'detect', '检测问题', '发现问题']):
        return await _anomaly(message_lower)

    # --- General Health Check (all services) — keep last, "health" is broad ---
    if any(kw in message_lower for kw in ['health', '健康', '状态检查', 'status check', '诊断', 'diagnose']):
        return _general_health()

    return None


# =========================================================================
# Private helpers
# =========================================================================

def _ec2_health() -> str:
    ops = _get_ops()
    if not ops:
        return "❌ AWS Ops module not available"
    try:
        health = ops.ec2_health_check()
        response = f"""🏥 **EC2 健康检查** (Region: {get_current_region()})

**整体状态:** {'✅ Healthy' if health['overall_status'] == 'healthy' else '⚠️ ' + health['overall_status'].upper()}

| Name | ID | State | Health | CPU | Issues |
|------|----| ------|--------|-----|--------|"""
        for inst in health.get('instances', [])[:10]:
            health_icon = "✅" if inst['health'] == 'healthy' else "⚠️" if inst['health'] == 'warning' else "❌"
            issues_str = ", ".join(inst.get('issues', [])[:2]) or "None"
            response += f"\n| {inst['name'][:15]} | {inst['id']} | {inst['state']} | {health_icon} | {inst.get('cpu_avg', 0):.1f}% | {issues_str[:20]} |"
        if health.get('issues'):
            response += f"\n\n**发现问题 ({len(health['issues'])}):**"
            for issue in health['issues'][:5]:
                response += f"\n- {issue['resource']}: {issue['issue']}"
        return response
    except Exception as e:
        return f"❌ EC2 健康检查失败: {str(e)}"


def _rds_health() -> str:
    ops = _get_ops()
    if not ops:
        return "❌ AWS Ops module not available"
    try:
        health = ops.rds_health_check()
        response = f"""🏥 **RDS 健康检查** (Region: {get_current_region()})

**整体状态:** {'✅ Healthy' if health['overall_status'] == 'healthy' else '⚠️ ' + health['overall_status'].upper()}

| ID | Engine | Status | Health | CPU | Connections | Issues |
|----|--------|--------|--------|-----|-------------|--------|"""
        for db in health.get('databases', []):
            health_icon = "✅" if db['health'] == 'healthy' else "⚠️" if db['health'] == 'warning' else "❌"
            issues_str = ", ".join(db.get('issues', [])[:2]) or "None"
            response += f"\n| {db['id']} | {db['engine'][:15]} | {db['status']} | {health_icon} | {db.get('cpu_avg', 0):.1f}% | {db.get('connections', 0):.0f} | {issues_str[:15]} |"
        if health.get('issues'):
            response += f"\n\n**发现问题 ({len(health['issues'])}):**"
            for issue in health['issues'][:5]:
                response += f"\n- {issue['resource']}: {issue['issue']}"
        return response
    except Exception as e:
        return f"❌ RDS 健康检查失败: {str(e)}"


def _lambda_health() -> str:
    ops = _get_ops()
    if not ops:
        return "❌ AWS Ops module not available"
    try:
        health = ops.lambda_health_check()
        response = f"""🏥 **Lambda 健康检查** (Region: {get_current_region()})

**整体状态:** {'✅ Healthy' if health['overall_status'] == 'healthy' else '⚠️ ' + health['overall_status'].upper()}

| Function | Health | Invocations | Errors | Error Rate | Throttles |
|----------|--------|-------------|--------|------------|-----------|"""
        for func in health.get('functions', [])[:10]:
            health_icon = "✅" if func['health'] == 'healthy' else "⚠️" if func['health'] == 'warning' else "❌"
            response += f"\n| {func['name'][:25]} | {health_icon} | {func.get('invocations', 0):.0f} | {func.get('errors', 0):.0f} | {func.get('error_rate', 0):.1f}% | {func.get('throttles', 0):.0f} |"
        if health.get('issues'):
            response += f"\n\n**发现问题 ({len(health['issues'])}):**"
            for issue in health['issues'][:5]:
                response += f"\n- {issue['resource']}: {issue['issue']}"
        return response
    except Exception as e:
        return f"❌ Lambda 健康检查失败: {str(e)}"


def _s3_health() -> str:
    ops = _get_ops()
    if not ops:
        return "❌ AWS Ops module not available"
    try:
        health = ops.s3_health_check()
        response = f"""🏥 **S3 健康检查**

**整体状态:** {'✅ Healthy' if health['overall_status'] == 'healthy' else '⚠️ ' + health['overall_status'].upper()}
**公开桶数量:** {health.get('public_buckets', 0)} {'⚠️' if health.get('public_buckets', 0) > 0 else ''}

| Bucket | Public | Encryption | Versioning | Issues |
|--------|--------|------------|------------|--------|"""
        for bucket in health.get('buckets', [])[:15]:
            public_icon = "⚠️ Yes" if bucket['public'] else "No"
            issues_str = ", ".join(bucket.get('issues', [])) or "None"
            response += f"\n| {bucket['name'][:30]} | {public_icon} | {bucket.get('encryption', 'N/A')} | {bucket.get('versioning', 'N/A')} | {issues_str[:15]} |"
        return response
    except Exception as e:
        return f"❌ S3 健康检查失败: {str(e)}"


def _vpc_health() -> str:
    ops = _get_ops()
    if not ops:
        return "❌ AWS Ops module not available"
    try:
        health = ops.vpc_health_check()
        response = f"""🏥 **VPC 健康检查** (Region: {get_current_region()})

**整体状态:** {'✅ Healthy' if health['overall_status'] == 'healthy' else '⚠️ ' + health['overall_status'].upper()}

| Name | ID | State | Subnets | IGW | NAT | Issues |
|------|----| ------|---------|-----|-----|--------|"""
        for vpc in health.get('vpcs', [])[:10]:
            igw = "✅" if vpc['has_igw'] else "❌"
            issues_str = ", ".join(vpc.get('issues', [])[:2]) or "None"
            response += f"\n| {vpc['name'][:15]} | {vpc['id']} | {vpc['state']} | {vpc['subnets_available']}/{vpc['subnets_count']} | {igw} | {vpc['nat_gateways']} | {issues_str[:15]} |"
        return response
    except Exception as e:
        return f"❌ VPC 健康检查失败: {str(e)}"


def _elb_health() -> str:
    ops = _get_ops()
    if not ops:
        return "❌ AWS Ops module not available"
    try:
        health = ops.elb_health_check()
        response = f"""🏥 **ELB 健康检查** (Region: {get_current_region()})

**整体状态:** {'✅ Healthy' if health['overall_status'] == 'healthy' else '⚠️ ' + health['overall_status'].upper()}

| Name | Type | State | Targets | Unhealthy | Issues |
|------|------|-------|---------|-----------|--------|"""
        for lb in health.get('load_balancers', [])[:10]:
            issues_str = ", ".join(lb.get('issues', [])[:2]) or "None"
            response += f"\n| {lb['name'][:20]} | {lb['type']} | {lb['state']} | {lb['total_targets']} | {lb['unhealthy_targets']} | {issues_str[:15]} |"
        return response
    except Exception as e:
        return f"❌ ELB 健康检查失败: {str(e)}"


def _route53_health() -> str:
    ops = _get_ops()
    if not ops:
        return "❌ AWS Ops module not available"
    try:
        health = ops.route53_health_check()
        response = f"""🏥 **Route 53 健康检查**

**整体状态:** {'✅ Healthy' if health['overall_status'] == 'healthy' else '⚠️ ' + health['overall_status'].upper()}

**Hosted Zones:** {len(health.get('hosted_zones', []))}
| Name | ID | Private | Records |
|------|----| --------|---------|"""
        for zone in health.get('hosted_zones', [])[:10]:
            private_tag = "✅" if zone.get('private') else ""
            response += f"\n| {zone['name'][:30]} | {zone['id']} | {private_tag} | {zone.get('record_count', 0)} |"
        hcs = health.get('health_checks', [])
        if hcs:
            response += f"\n\n**Health Checks:** {len(hcs)}"
            unhealthy = [hc for hc in hcs if hc['status'] != 'healthy']
            if unhealthy:
                response += f"\n⚠️ {len(unhealthy)} unhealthy health checks"
        return response
    except Exception as e:
        return f"❌ Route53 健康检查失败: {str(e)}"


def _dynamodb_health() -> str:
    ops = _get_ops()
    if not ops:
        return "❌ AWS Ops module not available"
    try:
        health = ops.dynamodb_health_check()
        response = f"""🏥 **DynamoDB 健康检查** (Region: {get_current_region()})

**整体状态:** {'✅ Healthy' if health['overall_status'] == 'healthy' else '⚠️ ' + health['overall_status'].upper()}

| Table | Status | Billing | RCU | WCU | Items | Issues |
|-------|--------|---------|-----|-----|-------|--------|"""
        for table in health.get('tables', [])[:10]:
            issues_str = ", ".join(table.get('issues', [])[:2]) or "None"
            response += f"\n| {table['name'][:15]} | {table['status']} | {table['billing_mode'][:10]} | {table['read_capacity']} | {table['write_capacity']} | {table['item_count']} | {issues_str[:15]} |"
        return response
    except Exception as e:
        return f"❌ DynamoDB 健康检查失败: {str(e)}"


def _ecs_health() -> str:
    ops = _get_ops()
    if not ops:
        return "❌ AWS Ops module not available"
    try:
        health = ops.ecs_health_check()
        response = f"""🏥 **ECS 健康检查** (Region: {get_current_region()})

**整体状态:** {'✅ Healthy' if health['overall_status'] == 'healthy' else '⚠️ ' + health['overall_status'].upper()}

| Cluster | Status | Running | Pending | Services | Issues |
|---------|--------|---------|---------|----------|--------|"""
        for cluster in health.get('clusters', [])[:10]:
            issues_str = ", ".join(cluster.get('issues', [])[:2]) or "None"
            response += f"\n| {cluster['name'][:15]} | {cluster['status']} | {cluster['running_tasks']} | {cluster['pending_tasks']} | {cluster['active_services']} | {issues_str[:15]} |"
        return response
    except Exception as e:
        return f"❌ ECS 健康检查失败: {str(e)}"


def _elasticache_health() -> str:
    ops = _get_ops()
    if not ops:
        return "❌ AWS Ops module not available"
    try:
        health = ops.elasticache_health_check()
        if health.get('error'):
            return f"⚠️ **ElastiCache 访问受限**\n\n{health['error']}"
        response = f"""🏥 **ElastiCache 健康检查** (Region: {get_current_region()})

**整体状态:** {'✅ Healthy' if health['overall_status'] == 'healthy' else '⚠️ ' + health['overall_status'].upper()}

| Cluster | Engine | Status | Nodes | Hit Ratio | Issues |
|---------|--------|--------|-------|-----------|--------|"""
        for cluster in health.get('clusters', [])[:10]:
            issues_str = ", ".join(cluster.get('issues', [])[:2]) or "None"
            response += f"\n| {cluster['id'][:15]} | {cluster['engine']} | {cluster['status']} | {cluster.get('num_nodes', 0)} | {cluster.get('hit_ratio', '-')}% | {issues_str[:15]} |"
        return response
    except Exception as e:
        return f"❌ ElastiCache 健康检查失败: {str(e)}"


async def _anomaly(message_lower: str) -> str:
    try:
        from src.event_correlator import get_correlator
        correlator = get_correlator(get_current_region())
        services = None
        for svc in ['ec2', 'rds', 'lambda']:
            if svc in message_lower:
                services = [svc]
                break
        event = await correlator.collect(services=services, lookback_minutes=15)
        return event.summary()
    except Exception as e:
        logger.warning("Event correlator failed, falling back: %s", e)
        ops = _get_ops()
        if not ops:
            return "❌ AWS Ops module not available"
    try:
        response = f"🔍 **异常检测报告** (Region: {get_current_region()})\n\n"
        total_anomalies = []
        for service in ['ec2', 'rds', 'lambda']:
            anomalies = ops.detect_anomalies(service)
            if anomalies.get('anomalies'):
                total_anomalies.extend(anomalies['anomalies'])
        if total_anomalies:
            response += f"**发现 {len(total_anomalies)} 个异常:**\n\n"
            response += "| 服务 | 资源 | 类型 | 值 | 严重性 |\n|------|------|------|-----|--------|\n"
            for a in total_anomalies[:10]:
                severity_icon = "🔴" if a['severity'] == 'critical' else "🟠" if a['severity'] == 'high' else "🟡"
                response += f"| {a.get('type', 'N/A').split('_')[0]} | {a['resource'][:20]} | {a['type']} | {a.get('value', 'N/A')} | {severity_icon} {a['severity']} |\n"
        else:
            response += "✅ **未发现异常！所有服务运行正常。**"
        return response
    except Exception as e:
        return f"❌ 异常检测失败: {str(e)}"


def _general_health() -> str:
    ops = _get_ops()
    if not ops:
        return "❌ AWS Ops module not available"
    try:
        response = f"🏥 **AWS 服务健康状态** (Region: {get_current_region()})\n\n"
        all_issues = []

        ec2_health = ops.ec2_health_check()
        ec2_status = "✅" if ec2_health['overall_status'] == 'healthy' else "⚠️" if ec2_health['overall_status'] == 'warning' else "❌"
        response += f"**EC2:** {ec2_status} {len(ec2_health.get('instances', []))} instances | Issues: {len(ec2_health.get('issues', []))}\n"
        all_issues.extend(ec2_health.get('issues', []))

        rds_health = ops.rds_health_check()
        rds_status = "✅" if rds_health['overall_status'] == 'healthy' else "⚠️" if rds_health['overall_status'] == 'warning' else "❌"
        response += f"**RDS:** {rds_status} {len(rds_health.get('databases', []))} databases | Issues: {len(rds_health.get('issues', []))}\n"
        all_issues.extend(rds_health.get('issues', []))

        lambda_health = ops.lambda_health_check()
        lambda_status = "✅" if lambda_health['overall_status'] == 'healthy' else "⚠️" if lambda_health['overall_status'] == 'warning' else "❌"
        response += f"**Lambda:** {lambda_status} {len(lambda_health.get('functions', []))} functions | Issues: {len(lambda_health.get('issues', []))}\n"
        all_issues.extend(lambda_health.get('issues', []))

        s3_health = ops.s3_health_check()
        s3_status = "✅" if s3_health['overall_status'] == 'healthy' else "⚠️"
        response += f"**S3:** {s3_status} {len(s3_health.get('buckets', []))} buckets | Public: {s3_health.get('public_buckets', 0)}\n"
        all_issues.extend(s3_health.get('issues', []))

        if all_issues:
            response += f"\n---\n**⚠️ 发现 {len(all_issues)} 个问题:**\n"
            for issue in all_issues[:10]:
                response += f"- {issue['resource']}: {issue['issue']}\n"
        else:
            response += "\n---\n✅ **所有服务运行正常！**"
        return response
    except Exception as e:
        return f"❌ 健康检查失败: {str(e)}"
