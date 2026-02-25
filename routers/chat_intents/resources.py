"""Resource listing intents: EC2, Lambda, S3, RDS, DynamoDB, ECS, ElastiCache, VPC, ELB, scan, account."""

import re
from typing import Optional

from routers.deps import get_scanner, get_current_region, set_current_region, logger


async def handle(message: str, message_lower: str) -> Optional[str]:
    """Route resource-listing intents.  Returns None if not matched."""

    scanner = get_scanner(get_current_region())

    # --- Help ---
    if any(kw in message_lower for kw in ['help', 'commands', '帮助', '命令']):
        return _help_text()

    # --- Scan all ---
    if any(kw in message_lower for kw in ['scan', '扫描', 'all resources', '所有资源']):
        return _scan_all(scanner)

    # --- Region switch ---
    region_match = re.search(r'region\s+([a-z]{2}-[a-z]+-\d)', message_lower)
    if region_match:
        new_region = region_match.group(1)
        set_current_region(new_region)
        return f"✅ Region 已切换到 **{new_region}**"

    # --- Account info ---
    if any(kw in message_lower for kw in ['account', '账号', '账户', 'who am i']):
        return _account_info(scanner)

    # --- EC2 list (skip if SOP or health command) ---
    if (any(kw in message_lower for kw in ['ec2', 'instance', '实例'])
            and not any(skip in message_lower for skip in [
                'sop list', 'sop show', 'sop suggest', 'sop run', 'sop 列表',
                'sop 详情', 'sop 推荐', 'sop 执行',
                'health', '健康', 'check', '检查', 'status',
                'start', 'stop', 'reboot', 'metrics', '指标', '监控'])):
        return _list_ec2(scanner)

    # --- Lambda list ---
    if (any(kw in message_lower for kw in ['lambda', '函数', 'function'])
            and not any(skip in message_lower for skip in [
                'health', '健康', 'check', '检查', 'invoke', '调用', '执行',
                'logs', '日志', 'metrics'])):
        return _list_lambda(scanner)

    # --- S3 list ---
    if (any(kw in message_lower for kw in ['s3', 'bucket', '桶', '存储'])
            and not any(skip in message_lower for skip in ['health', '健康', 'check', '检查'])):
        return _list_s3(scanner)

    # --- RDS list ---
    if (any(kw in message_lower for kw in ['rds', 'database', '数据库'])
            and not any(skip in message_lower for skip in [
                'health', '健康', 'check', '检查', 'reboot', 'failover',
                '故障转移', '重启', 'metrics', '指标'])):
        return _list_rds(scanner)

    # --- DynamoDB list ---
    if (any(kw in message_lower for kw in ['dynamodb', 'ddb', 'dynamo', '表'])
            and 'health' not in message_lower):
        return _list_dynamodb(scanner)

    # --- ECS list ---
    if (any(kw in message_lower for kw in ['ecs', 'container', '容器'])
            and 'health' not in message_lower):
        return _list_ecs(scanner)

    # --- ElastiCache list ---
    if (any(kw in message_lower for kw in ['elasticache', 'cache', 'redis', 'memcached', '缓存'])
            and 'health' not in message_lower):
        return _list_elasticache(scanner)

    # --- VPC list ---
    if (any(kw in message_lower for kw in ['vpc', '网络', 'network'])
            and 'health' not in message_lower):
        return _list_vpc(scanner)

    # --- ELB list ---
    if (any(kw in message_lower for kw in ['elb', 'load balancer', '负载均衡'])
            and 'health' not in message_lower):
        return _list_elb(scanner)

    return None


# =========================================================================
# Private helpers
# =========================================================================

def _help_text() -> str:
    from routers.deps import get_current_region
    return f"""📚 **AgenticAIOps Chat Commands**

**🔍 资源查询:**
| Command | Description |
|---------|-------------|
| `ec2` | 列出 EC2 实例 |
| `lambda` | 列出 Lambda 函数 |
| `s3` | 列出 S3 存储桶 |
| `rds` | 列出 RDS 数据库 |
| `dynamodb` | 列出 DynamoDB 表 |
| `ecs` | 列出 ECS 集群 |
| `elasticache` | 列出 ElastiCache 集群 |
| `vpc` | 列出 VPCs |
| `elb` | 列出负载均衡器 |
| `scan` | 扫描所有资源 |

**🏥 健康检查:**
| Command | Description |
|---------|-------------|
| `ec2 health` | EC2 健康检查 |
| `rds health` | RDS 健康检查 |
| `lambda health` | Lambda 健康检查 |
| `s3 health` | S3 健康检查 |
| `dynamodb health` | DynamoDB 健康检查 |
| `ecs health` | ECS 健康检查 |
| `elasticache health` | ElastiCache 健康检查 |
| `vpc health` | VPC 健康检查 |
| `elb health` | ELB 健康检查 |
| `route53 health` | Route53 健康检查 |
| `health` | 全服务健康检查 |
| `anomaly` | 异常检测 |

**⚙️ EC2 操作:**
| Command | Description |
|---------|-------------|
| `ec2 start i-xxx` | 启动实例 |
| `ec2 stop i-xxx` | 停止实例 |
| `ec2 reboot i-xxx` | 重启实例 |

**⚙️ RDS 操作:**
| Command | Description |
|---------|-------------|
| `rds reboot xxx` | 重启 RDS 实例 |
| `rds failover xxx` | RDS 故障转移 (Multi-AZ) |

**⚙️ Lambda 操作:**
| Command | Description |
|---------|-------------|
| `lambda invoke xxx` | 调用 Lambda 函数 |

**📊 监控:**
| Command | Description |
|---------|-------------|
| `ec2 metrics i-xxx` | EC2 指标 |
| `rds metrics xxx` | RDS 指标 |
| `lambda logs xxx` | Lambda 日志 |

**🔔 告警通知:**
| Command | Description |
|---------|-------------|
| `notification status` | 查看通知配置状态 |
| `test notification` | 发送测试通知 |
| `send alert <msg>` | 发送自定义告警 |

**🔧 其他:**
| Command | Description |
|---------|-------------|
| `account` | AWS 账号信息 |
| `region us-east-1` | 切换 Region |

当前 Region: **{get_current_region()}** | 支持服务: **13**"""


def _scan_all(scanner) -> str:
    try:
        results = scanner.scan_all_resources()
        response = f"""📊 **AWS 资源扫描报告**
Account: {results['account'].get('account_id', 'N/A')}
Region: {results['region']}

| 服务 | 数量 | 状态 |
|------|------|------|"""
        for service, data in results.get('services', {}).items():
            if 'error' not in data:
                count = data.get('count', 0)
                if 'status' in data:
                    status = f"{data['status'].get('running', 0)} running"
                elif 'public_count' in data and data['public_count'] > 0:
                    status = f"⚠️ {data['public_count']} public"
                else:
                    status = "OK"
                response += f"\n| {service.upper()} | {count} | {status} |"
        issues = results.get('summary', {}).get('issues_found', [])
        if issues:
            response += f"\n\n⚠️ **发现 {len(issues)} 个潜在问题**"
            for issue in issues[:3]:
                response += f"\n- [{issue['severity'].upper()}] {issue['service']}: {issue['type']}"
        return response
    except Exception as e:
        return f"❌ 扫描失败: {str(e)}"


def _account_info(scanner) -> str:
    try:
        data = scanner.get_account_info()
        return f"""🔐 **AWS Account Info**

- Account ID: `{data.get('account_id', 'N/A')}`
- ARN: `{data.get('arn', 'N/A')}`
- Current Region: `{get_current_region()}`"""
    except Exception as e:
        return f"❌ 获取账号信息失败: {str(e)}"


def _list_ec2(scanner) -> str:
    try:
        data = scanner._scan_ec2()
        response = f"""🖥️ **EC2 Instances** (Region: {get_current_region()})

Total: {data['count']} | Running: {data['status']['running']} | Stopped: {data['status']['stopped']}

| Name | ID | Type | State | IP |
|------|----|----- |-------|-----|"""
        for inst in data.get('instances', [])[:10]:
            response += f"\n| {inst['name'][:20]} | {inst['id']} | {inst['type']} | {inst['state']} | {inst.get('private_ip', 'N/A')} |"
        if data['count'] > 10:
            response += f"\n\n... 还有 {data['count'] - 10} 个实例"
        return response
    except Exception as e:
        return f"❌ 获取 EC2 失败: {str(e)}"


def _list_lambda(scanner) -> str:
    try:
        data = scanner._scan_lambda()
        response = f"""⚡ **Lambda Functions** (Region: {get_current_region()})

Total: {data['count']}

| Function | Runtime | Memory | Timeout |
|----------|---------|--------|---------|"""
        for func in data.get('functions', [])[:10]:
            response += f"\n| {func['name'][:30]} | {func['runtime']} | {func['memory']}MB | {func['timeout']}s |"
        return response
    except Exception as e:
        return f"❌ 获取 Lambda 失败: {str(e)}"


def _list_s3(scanner) -> str:
    try:
        data = scanner._scan_s3()
        response = f"""📁 **S3 Buckets**

Total: {data['count']} | Public: {data.get('public_count', 0)} ⚠️

| Bucket Name | Public |
|-------------|--------|"""
        for bucket in data.get('buckets', [])[:15]:
            public_tag = "⚠️ Yes" if bucket.get('public') else "No"
            response += f"\n| {bucket['name'][:40]} | {public_tag} |"
        if data['count'] > 15:
            response += f"\n\n... 还有 {data['count'] - 15} 个桶"
        return response
    except Exception as e:
        return f"❌ 获取 S3 失败: {str(e)}"


def _list_rds(scanner) -> str:
    try:
        data = scanner._scan_rds()
        response = f"""🗄️ **RDS Databases** (Region: {get_current_region()})

Total: {data['count']}

| ID | Engine | Class | Status | Public |
|----|--------|-------|--------|--------|"""
        for db in data.get('instances', []):
            public_tag = "⚠️ Yes" if db.get('public') else "No"
            response += f"\n| {db['id']} | {db['engine']} | {db['class']} | {db['status']} | {public_tag} |"
        return response
    except Exception as e:
        return f"❌ 获取 RDS 失败: {str(e)}"


def _list_dynamodb(scanner) -> str:
    try:
        data = scanner._scan_dynamodb()
        if data.get('error'):
            return f"⚠️ **DynamoDB 访问受限**\n\n{data['error']}\n\n*需要 IAM 权限: dynamodb:ListTables, dynamodb:DescribeTable*"
        response = f"""📊 **DynamoDB Tables** (Region: {get_current_region()})

Total: {data['count']}

| Table | Status | Billing | RCU | WCU | Items |
|-------|--------|---------|-----|-----|-------|"""
        for table in data.get('tables', [])[:15]:
            response += f"\n| {table['name'][:20]} | {table['status']} | {table.get('billing_mode', 'N/A')[:10]} | {table.get('read_capacity', 0)} | {table.get('write_capacity', 0)} | {table.get('item_count', 0)} |"
        if data['count'] > 15:
            response += f"\n\n... 还有 {data['count'] - 15} 个表"
        return response
    except Exception as e:
        return f"❌ 获取 DynamoDB 失败: {str(e)}"


def _list_ecs(scanner) -> str:
    try:
        data = scanner._scan_ecs()
        if data.get('error'):
            return f"⚠️ **ECS 访问受限**\n\n{data['error']}\n\n*需要 IAM 权限: ecs:ListClusters, ecs:DescribeClusters*"
        response = f"""🐳 **ECS Clusters** (Region: {get_current_region()})

Total: {data['count']}

| Cluster | Status | Running | Pending | Services |
|---------|--------|---------|---------|----------|"""
        for cluster in data.get('clusters', [])[:10]:
            response += f"\n| {cluster['name'][:20]} | {cluster['status']} | {cluster['running_tasks']} | {cluster['pending_tasks']} | {cluster['active_services']} |"
        return response
    except Exception as e:
        return f"❌ 获取 ECS 失败: {str(e)}"


def _list_elasticache(scanner) -> str:
    try:
        data = scanner._scan_elasticache()
        if data.get('error'):
            return f"⚠️ **ElastiCache 访问受限**\n\n{data['error']}\n\n*需要 IAM 权限: elasticache:DescribeCacheClusters*"
        response = f"""🗄️ **ElastiCache Clusters** (Region: {get_current_region()})

Total: {data['count']}

| Cluster | Engine | Version | Status | Type | Nodes |
|---------|--------|---------|--------|------|-------|"""
        for cluster in data.get('clusters', [])[:10]:
            response += f"\n| {cluster['id'][:15]} | {cluster['engine']} | {cluster.get('engine_version', '-')} | {cluster['status']} | {cluster.get('node_type', cluster.get('type', '-'))} | {cluster.get('num_nodes', 0)} |"
        return response
    except Exception as e:
        return f"❌ 获取 ElastiCache 失败: {str(e)}"


def _list_vpc(scanner) -> str:
    try:
        data = scanner._scan_vpc()
        response = f"""🌐 **VPCs** (Region: {get_current_region()})

Total: {data['count']}

| Name | ID | CIDR | State | Default |
|------|----| -----|-------|---------|"""
        for vpc in data.get('vpcs', []):
            default_tag = "✅" if vpc.get('is_default') else ""
            response += f"\n| {vpc['name'][:20]} | {vpc['id']} | {vpc['cidr']} | {vpc['state']} | {default_tag} |"
        return response
    except Exception as e:
        return f"❌ 获取 VPC 失败: {str(e)}"


def _list_elb(scanner) -> str:
    try:
        data = scanner._scan_elb()
        response = f"""⚖️ **Load Balancers** (Region: {get_current_region()})

Total: {data['count']} | Active: {data.get('status', {}).get('active', 0)}

| Name | Type | Scheme | State | DNS |
|------|------|--------|-------|-----|"""
        for lb in data.get('load_balancers', [])[:10]:
            response += f"\n| {lb['name'][:20]} | {lb['type']} | {lb['scheme']} | {lb['state']} | {lb['dns_name'][:30]}... |"
        return response
    except Exception as e:
        return f"❌ 获取 ELB 失败: {str(e)}"
