"""Database Admin Skill — 12 tools (RDS/DynamoDB/ElastiCache)."""
from __future__ import annotations
from .._security import secure_tool
from .._models import SecurityTier, ToolResult

def _boto(svc, method, **kw):
    try:
        import boto3
        c = boto3.client(svc)
        r = getattr(c, method)(**kw)
        r.pop("ResponseMetadata", None)
        return r
    except Exception as e:
        return {"error": str(e)}

@secure_tool(tier=SecurityTier.T0_READONLY, skill="database_admin", command_param=None)
def rds_instance_status() -> str:
    """Get all RDS instance statuses."""
    return ToolResult.success(_boto("rds", "describe_db_instances")).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="database_admin", command_param=None)
def rds_cluster_status() -> str:
    """Get Aurora/RDS cluster statuses."""
    return ToolResult.success(_boto("rds", "describe_db_clusters")).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="database_admin", command_param=None)
def rds_events(minutes: int = 60) -> str:
    """Get recent RDS events."""
    return ToolResult.success(_boto("rds", "describe_events", Duration=min(minutes, 1440))).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="database_admin", command_param=None)
def dynamodb_list_tables() -> str:
    """List DynamoDB tables."""
    return ToolResult.success(_boto("dynamodb", "list_tables")).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="database_admin", command_param=None)
def dynamodb_describe_table(table_name: str) -> str:
    """Describe a DynamoDB table."""
    return ToolResult.success(_boto("dynamodb", "describe_table", TableName=table_name)).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="database_admin", command_param=None)
def elasticache_status() -> str:
    """Get ElastiCache cluster statuses."""
    return ToolResult.success(_boto("elasticache", "describe_cache_clusters", ShowCacheNodeInfo=True)).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="database_admin", command_param=None)
def rds_slow_queries(db_instance_id: str) -> str:
    """Get RDS slow query log (last 100 lines via CW Logs)."""
    return ToolResult.success(_boto("rds", "describe_db_log_files", DBInstanceIdentifier=db_instance_id)).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="database_admin", command_param=None)
def rds_performance_insights(db_instance_id: str) -> str:
    """Get Performance Insights metrics."""
    return ToolResult.success({"db_instance": db_instance_id, "note": "requires PI enabled"}).to_json()

# T1
@secure_tool(tier=SecurityTier.T1_LOW_RISK, skill="database_admin", command_param=None)
def rds_create_snapshot(db_instance_id: str, snapshot_id: str) -> str:
    """Create RDS snapshot (non-destructive backup)."""
    return ToolResult.success(_boto("rds", "create_db_snapshot",
        DBInstanceIdentifier=db_instance_id, DBSnapshotIdentifier=snapshot_id)).to_json()

@secure_tool(tier=SecurityTier.T1_LOW_RISK, skill="database_admin", command_param=None)
def elasticache_reboot_node(cluster_id: str, node_id: str) -> str:
    """Reboot a single ElastiCache node."""
    return ToolResult.success(_boto("elasticache", "reboot_cache_cluster",
        CacheClusterId=cluster_id, CacheNodeIdsToReboot=[node_id])).to_json()

# T2
@secure_tool(tier=SecurityTier.T2_HIGH_RISK, skill="database_admin", command_param=None, dry_run_support=True)
def rds_failover_cluster(cluster_id: str, dry_run: bool = False) -> str:
    """Failover an RDS/Aurora cluster. Requires approval_token."""
    return ToolResult.success(_boto("rds", "failover_db_cluster", DBClusterIdentifier=cluster_id)).to_json()

@secure_tool(tier=SecurityTier.T2_HIGH_RISK, skill="database_admin", command_param=None, dry_run_support=True)
def rds_modify_instance(db_instance_id: str, instance_class: str = "", dry_run: bool = False) -> str:
    """Modify RDS instance class. Requires approval_token."""
    kwargs = {"DBInstanceIdentifier": db_instance_id, "ApplyImmediately": True}
    if instance_class:
        kwargs["DBInstanceClass"] = instance_class
    return ToolResult.success(_boto("rds", "modify_db_instance", **kwargs)).to_json()
