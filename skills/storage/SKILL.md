---
name: storage
description: >
  Diagnose and manage storage systems including EBS volumes, EFS, S3,
  FSx, and local disk. Use when investigating disk full, I/O bottlenecks,
  IOPS throttling, snapshot management, or backup issues.
license: Apache-2.0
compatibility: Requires AWS CLI + local disk utilities
metadata:
  author: agenticaiops
  version: "1.0"
  routing:
    domains: [storage, ebs, efs, s3, fsx, disk, volume, snapshot, iops, throughput, mount, nfs, gp3, io2, st1, sc1]
    keywords: [DiskFull, NoSpaceLeft, IOPSThrottled, BurstBalanceExhausted, VolumeAttachFailed, SnapshotFailed, S3SlowDown, MountFailed, FilesystemCorrupt, NFSStale]
    confidence_boost: 0.15
safety:
  tiers:
    read: [describe_volumes, describe_snapshots, describe_efs, list_s3_objects, df_usage, lsblk_info, iostat_stats, check_mount, describe_fsx, get_volume_metrics]
    write: [create_snapshot, modify_volume, put_lifecycle, tag_volume, mount_filesystem, resize_filesystem, create_efs_access_point]
    dangerous: [delete_volume, delete_snapshot, force_detach_volume, delete_s3_objects, delete_efs, umount_force, mkfs_format]
  security_filter: storage
allowed-tools: Bash(aws:ec2,efs,s3,fsx,cloudwatch) Bash(shell:df,du,lsblk,mount,umount,iostat,fio,blkid,fdisk,lvs,vgs,pvs)
---

# Storage Operations Skill

You are a storage operations expert covering AWS cloud storage and Linux
filesystem administration.

## Principles

1. **Measure before resize** — get actual usage and IOPS data first
2. **Snapshot before modify** — always snapshot before resizing volumes
3. **Burst balance awareness** — gp2/gp3 have burst credit limits; check BurstBalance
4. **IOPS ≠ throughput** — diagnose which is the bottleneck
5. **Never force-umount in production** — prefer graceful
6. **S3 is eventually consistent for deletes**

<!-- tier: read -->
## Diagnostics

### Local Disk
```bash
df -hT
du -sh /var/log/* | sort -rh | head -20
lsblk -f
iostat -xz 5 3
dmesg | grep -i "error\|fail\|i/o" | tail -20
```

### EBS Volume
```bash
aws ec2 describe-volumes --volume-ids <vol-id>
aws cloudwatch get-metric-statistics --namespace AWS/EBS --metric-name BurstBalance --dimensions Name=VolumeId,Value=<vol-id> --start-time <T> --end-time <T> --period 300 --statistics Average
```

### S3
```bash
aws s3api head-bucket --bucket <bucket>
aws s3 ls s3://<bucket>/ --summarize --human-readable
```

<!-- tier: write -->
## Remediation

```bash
aws ec2 create-snapshot --volume-id <vol-id> --description "Pre-modify backup"
aws ec2 modify-volume --volume-id <vol-id> --volume-type gp3 --size <new-size> --iops <target>
sudo growpart /dev/xvda 1
sudo resize2fs /dev/xvda1
```

<!-- tier: dangerous -->
## Destructive Operations (requires approval)

- `delete-volume` — permanently destroys data
- `force-detach-volume` — can corrupt filesystem
- `mkfs` — reformats device, erases all data

## Common Patterns

| Symptom | Likely Cause | First Check |
|---------|-------------|-------------|
| No space left on device | Disk full or inode exhaustion | df -hT + df -i |
| High I/O wait | IOPS throttling | iostat + BurstBalance |
| EFS slow | Burst credits exhausted | BurstCreditBalance |
| Volume stuck in-use | Unclean detach | describe-volumes |
