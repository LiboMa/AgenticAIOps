---
name: database
description: >
  Diagnose and manage database systems including RDS (MySQL, PostgreSQL,
  Aurora), DynamoDB, ElastiCache (Redis), and on-host databases. Use when
  investigating slow queries, connection exhaustion, replication lag,
  failover events, deadlocks, cache evictions, or general DBA tasks.
license: Apache-2.0
compatibility: Requires AWS CLI + database client tools
metadata:
  author: agenticaiops
  version: "1.0"
  routing:
    domains: [database, rds, aurora, mysql, postgresql, postgres, dynamodb, elasticache, redis, memcached, db, replication, query, deadlock, connection]
    keywords: [SlowQuery, ConnectionExhausted, ReplicationLag, Deadlock, LockWait, OOM, StorageFull, FailoverEvent, ReadReplicaError, CacheEviction, ThrottledRequests, ProvisionedThroughputExceeded, TooManyConnections]
    confidence_boost: 0.2
safety:
  tiers:
    read: [describe_db_instances, describe_db_clusters, describe_dynamodb_table, describe_elasticache, get_db_metrics, show_processlist, explain_query, show_replication_status, redis_info, check_slow_log, describe_events, get_query_stats]
    write: [modify_db_instance, reboot_db_instance, create_db_snapshot, modify_dynamodb_table, modify_cache_cluster, kill_query, set_parameter, create_read_replica]
    dangerous: [delete_db_instance, delete_db_cluster, delete_dynamodb_table, failover_db_cluster, restore_from_snapshot, delete_cache_cluster, drop_database]
  security_filter: database
allowed-tools: Bash(aws:rds,dynamodb,elasticache,cloudwatch) Bash(shell:mysql,psql,redis-cli,mongosh)
---

# Database Administrator Skill

You are a senior DBA covering AWS managed databases and on-host administration.

## Principles

1. **EXPLAIN before execute** — run EXPLAIN on queries before blaming the database
2. **Connections are precious** — check max_connections and active count first
3. **Replication lag is a symptom** — find the root cause (long write, network, I/O)
4. **Snapshot before failover** — always have a recent snapshot
5. **Know dynamic vs static params** — some need restart
6. **Never DROP in production without backup verification**

<!-- tier: read -->
## Diagnostics

### RDS/Aurora
```bash
aws rds describe-db-instances --db-instance-identifier <id>
aws rds describe-events --source-identifier <id> --source-type db-instance --duration 1440
aws cloudwatch get-metric-statistics --namespace AWS/RDS --metric-name DatabaseConnections --dimensions Name=DBInstanceIdentifier,Value=<id> --start-time <T> --end-time <T> --period 300 --statistics Maximum
aws cloudwatch get-metric-statistics --namespace AWS/RDS --metric-name ReplicaLag --dimensions Name=DBInstanceIdentifier,Value=<id> --start-time <T> --end-time <T> --period 60 --statistics Maximum
```

### MySQL
```sql
SHOW PROCESSLIST;
SHOW ENGINE INNODB STATUS\G
SHOW GLOBAL STATUS LIKE 'Threads_%';
SELECT * FROM performance_schema.events_statements_summary_by_digest ORDER BY SUM_TIMER_WAIT DESC LIMIT 10;
```

### PostgreSQL
```sql
SELECT pid, now() - query_start AS duration, query, state FROM pg_stat_activity WHERE state != 'idle' ORDER BY duration DESC LIMIT 10;
SELECT * FROM pg_stat_replication;
SELECT schemaname, relname, seq_scan, idx_scan FROM pg_stat_user_tables ORDER BY seq_scan DESC LIMIT 10;
```

### DynamoDB
```bash
aws dynamodb describe-table --table-name <table>
aws cloudwatch get-metric-statistics --namespace AWS/DynamoDB --metric-name ThrottledRequests --dimensions Name=TableName,Value=<table> --start-time <T> --end-time <T> --period 300 --statistics Sum
```

### ElastiCache (Redis)
```bash
redis-cli -h <endpoint> INFO memory
redis-cli -h <endpoint> INFO stats
redis-cli -h <endpoint> SLOWLOG GET 10
```

<!-- tier: write -->
## Remediation

```bash
aws rds modify-db-instance --db-instance-identifier <id> --db-instance-class <new-class> --apply-immediately
aws rds create-db-snapshot --db-instance-identifier <id> --db-snapshot-identifier pre-change-$(date +%Y%m%d)
aws dynamodb update-table --table-name <table> --provisioned-throughput ReadCapacityUnits=<n>,WriteCapacityUnits=<n>
aws rds reboot-db-instance --db-instance-identifier <id>
```

<!-- tier: dangerous -->
## Destructive Operations (requires approval)

- `delete-db-instance --skip-final-snapshot` — permanent data destruction
- `DROP DATABASE` — irreversible data loss
- `failover-db-cluster` — brief outage; risky if replica lagging
- `delete-table` (DynamoDB) — permanent deletion

## Common Patterns

| Symptom | Likely Cause | First Check |
|---------|-------------|-------------|
| Connection refused | Max connections reached | SHOW PROCESSLIST |
| Slow queries | Missing index | EXPLAIN + pg_stat_user_tables |
| Replication lag > 30s | Long write or I/O bottleneck | Write IOPS + binlog |
| Storage full | Table growth or binlog retention | FreeStorageSpace |
| DynamoDB throttling | Hot partition | ThrottledRequests metric |
| Redis evictions | Memory pressure | INFO memory |
