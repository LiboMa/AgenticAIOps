"""Storage Skill — 10 tools (S3/EBS/EFS/local filesystem)."""
from __future__ import annotations
from .._security import secure_tool
from .._models import SecurityTier, ToolResult
from .._executor import ShellExecutor

_shell = ShellExecutor(timeout=30)

def _boto(svc, method, **kw):
    try:
        import boto3; c = boto3.client(svc); r = getattr(c, method)(**kw); r.pop("ResponseMetadata", None); return r
    except Exception as e: return {"error": str(e)}

@secure_tool(tier=SecurityTier.T0_READONLY, skill="storage", command_param=None)
def storage_list_buckets() -> str:
    """List all S3 buckets with size summary."""
    return ToolResult.success(_boto("s3", "list_buckets")).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="storage", command_param=None)
def s3_list_objects(bucket: str, prefix: str = "", max_keys: int = 50) -> str:
    """List objects in an S3 bucket."""
    return ToolResult.success(_boto("s3", "list_objects_v2",
        Bucket=bucket, Prefix=prefix, MaxKeys=min(max_keys, 200))).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="storage", command_param=None)
def ebs_describe_volumes(filters: str = "") -> str:
    """Describe EBS volumes."""
    return ToolResult.success(_boto("ec2", "describe_volumes")).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="storage", command_param=None)
def efs_describe_filesystems() -> str:
    """Describe EFS file systems."""
    return ToolResult.success(_boto("efs", "describe_file_systems")).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="storage", command_param=None)
def local_disk_usage(path: str = "/") -> str:
    """Local disk usage analysis."""
    df = _shell.execute(f"df -h {path}")
    du = _shell.execute(f"du -sh {path}/* 2>/dev/null | sort -rh | head -20")
    return ToolResult.success({"df": df.stdout, "top_dirs": du.stdout}).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="storage", command_param=None)
def ebs_snapshot_list(volume_id: str = "") -> str:
    """List EBS snapshots."""
    kwargs = {"OwnerIds": ["self"]}
    if volume_id:
        kwargs["Filters"] = [{"Name": "volume-id", "Values": [volume_id]}]
    return ToolResult.success(_boto("ec2", "describe_snapshots", **kwargs)).to_json()

@secure_tool(tier=SecurityTier.T0_READONLY, skill="storage", command_param=None)
def s3_bucket_policy(bucket: str) -> str:
    """Get S3 bucket policy."""
    return ToolResult.success(_boto("s3", "get_bucket_policy", Bucket=bucket)).to_json()

# T1
@secure_tool(tier=SecurityTier.T1_LOW_RISK, skill="storage", command_param=None)
def ebs_create_snapshot(volume_id: str, description: str = "AIOps snapshot") -> str:
    """Create EBS snapshot (non-destructive backup)."""
    return ToolResult.success(_boto("ec2", "create_snapshot",
        VolumeId=volume_id, Description=description)).to_json()

# T2
@secure_tool(tier=SecurityTier.T2_HIGH_RISK, skill="storage", command_param=None, dry_run_support=True)
def ebs_delete_snapshot(snapshot_id: str, dry_run: bool = False) -> str:
    """Delete an EBS snapshot. Requires approval_token."""
    return ToolResult.success(_boto("ec2", "delete_snapshot",
        SnapshotId=snapshot_id, DryRun=dry_run)).to_json()

@secure_tool(tier=SecurityTier.T2_HIGH_RISK, skill="storage", command_param=None, dry_run_support=True)
def s3_delete_objects(bucket: str, prefix: str, dry_run: bool = False) -> str:
    """Delete objects in S3 by prefix. Requires approval_token."""
    if dry_run:
        objs = _boto("s3", "list_objects_v2", Bucket=bucket, Prefix=prefix, MaxKeys=10)
        return ToolResult.success({"action": "would_delete", "preview": objs}).to_json()
    return ToolResult.success({"bucket": bucket, "prefix": prefix, "action": "delete"}).to_json()
