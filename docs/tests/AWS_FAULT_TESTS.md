# AWS 故障测试场景文档

> 基于真实 AWS 环境数据生成
> 生成日期: 2026-02-10

## 环境概述

### 真实资源清单
| 资源类型 | 数量 | 示例 |
|---------|------|------|
| EC2 实例 | 14 | i-080ab08eefa16b539 (mbot-sg-1), i-0e6da7fadd619d0a7 (jump-ab2-db-proxy) |
| Lambda 函数 | 7+ | pet-store-PetStoreFunction, SensativeAPI |
| ALB/NLB | 7 | alb-lambda-pets, ASG-Nginx-ALB |
| VPC | 6 | vpc-028fe79b3785c1aba (project-vpc) |
| DynamoDB | 4 | FrrSensor, Music |
| 活跃告警 | 6 | DynamoDB 容量告警 |

---

## 测试场景 1: EC2 实例故障

### 场景 1.1: EC2 高 CPU 利用率
**目标实例:** `i-080ab08eefa16b539` (mbot-sg-1, m6i.xlarge, running)

**注入故障步骤:**
```bash
# 1. SSH 到目标实例
ssh -i <key.pem> ubuntu@<instance-ip>

# 2. 使用 stress 工具注入 CPU 负载
sudo apt-get install -y stress
stress --cpu 4 --timeout 300  # 4核满载 5分钟

# 3. 验证 CPU 使用率
top -bn1 | head -5
```

**预期检测:**
- CloudWatch CPUUtilization > 80%
- 系统应自动触发告警
- AIOps 平台应检测并推荐 SOP

**测试命令:**
```
# 在 AIOps Chat 中执行
ec2 health
ec2 metrics i-080ab08eefa16b539
sop suggest ec2 high cpu
```

**清理步骤:**
```bash
# 停止 stress 进程
pkill stress
```

---

### 场景 1.2: EC2 内存不足 (OOM)
**目标实例:** `i-0e6da7fadd619d0a7` (jump-ab2-db-proxy, m5.xlarge, running)

**注入故障步骤:**
```bash
# 1. SSH 到目标实例
ssh -i <key.pem> ubuntu@<instance-ip>

# 2. 消耗内存
stress --vm 2 --vm-bytes 3G --timeout 300

# 3. 监控内存
free -h
```

**预期检测:**
- CloudWatch MemoryUtilization > 90%
- 系统日志出现 OOM 警告

**测试命令:**
```
ec2 health
sop suggest ec2 memory
```

---

### 场景 1.3: EC2 磁盘空间不足
**目标实例:** `i-080ab08eefa16b539` (mbot-sg-1)

**注入故障步骤:**
```bash
# 1. 创建大文件填满磁盘
dd if=/dev/zero of=/tmp/bigfile bs=1G count=50

# 2. 检查磁盘使用
df -h
```

**预期检测:**
- 磁盘使用率 > 90%
- CloudWatch DiskSpaceUtilization 告警

**测试命令:**
```
ec2 health
```

**清理步骤:**
```bash
rm /tmp/bigfile
```

---

## 测试场景 2: Lambda 函数故障

### 场景 2.1: Lambda 超时
**目标函数:** `pet-store-PetStoreFunction-YwXsum9ltfg7`

**注入故障步骤:**
```bash
# 1. 临时修改函数超时为 3 秒
aws lambda update-function-configuration \
  --function-name pet-store-PetStoreFunction-YwXsum9ltfg7 \
  --timeout 3

# 2. 触发函数执行 (带延迟处理)
aws lambda invoke \
  --function-name pet-store-PetStoreFunction-YwXsum9ltfg7 \
  --payload '{"delay": 5000}' \
  response.json
```

**预期检测:**
- Lambda 错误率上升
- CloudWatch Errors 指标增加
- Duration 接近超时值

**测试命令:**
```
lambda
lambda health
sop suggest lambda timeout
```

**清理步骤:**
```bash
# 恢复原超时设置
aws lambda update-function-configuration \
  --function-name pet-store-PetStoreFunction-YwXsum9ltfg7 \
  --timeout 30
```

---

### 场景 2.2: Lambda 内存不足
**目标函数:** `SensativeAPI` (128MB)

**注入故障步骤:**
```bash
# 内存已经很小 (128MB)，执行大负载请求即可触发
# 修改代码添加内存消耗逻辑，或直接发送大 payload
aws lambda invoke \
  --function-name SensativeAPI \
  --payload '{"data": "'$(python3 -c "print('x'*100000000)")'"}' \
  response.json
```

**预期检测:**
- 函数因 OOM 失败
- CloudWatch 错误指标增加

---

## 测试场景 3: 负载均衡器故障

### 场景 3.1: ALB 后端不健康
**目标 ALB:** `alb-lambda-pets`

**注入故障步骤:**
```bash
# 1. 获取目标组
TG_ARN=$(aws elbv2 describe-target-groups \
  --names alb-lambda-pets-tg \
  --query 'TargetGroups[0].TargetGroupArn' --output text)

# 2. 检查当前健康状态
aws elbv2 describe-target-health --target-group-arn $TG_ARN

# 3. 修改健康检查使其失败 (临时)
aws elbv2 modify-target-group \
  --target-group-arn $TG_ARN \
  --health-check-path /nonexistent
```

**预期检测:**
- 目标组显示 unhealthy
- ELB 健康检查告警

**测试命令:**
```
elb
elb health
sop suggest alb unhealthy
```

**清理步骤:**
```bash
# 恢复健康检查路径
aws elbv2 modify-target-group \
  --target-group-arn $TG_ARN \
  --health-check-path /health
```

---

### 场景 3.2: ALB 5xx 错误率飙升
**目标 ALB:** `ASG-Nginx-ALB`

**注入故障步骤:**
```bash
# 模拟后端返回 500 错误
# 需要在后端服务配置返回错误

# 或者发送大量请求触发限流
for i in {1..1000}; do
  curl -s http://<alb-dns>/api/test &
done
wait
```

**预期检测:**
- HTTPCode_ELB_5XX_Count 增加
- CloudWatch 5XX 告警

---

## 测试场景 4: 网络故障

### 场景 4.1: VPC 安全组规则变更
**目标 VPC:** `vpc-028fe79b3785c1aba` (project-vpc)

**注入故障步骤:**
```bash
# 1. 临时移除安全组入站规则
SG_ID="sg-05b91c933f703cc72"  # launch-wizard-4

# 备份当前规则
aws ec2 describe-security-groups --group-ids $SG_ID > /tmp/sg_backup.json

# 移除 SSH 入站规则
aws ec2 revoke-security-group-ingress \
  --group-id $SG_ID \
  --protocol tcp \
  --port 22 \
  --cidr 0.0.0.0/0
```

**预期检测:**
- 连接超时
- VPC Flow Logs 显示 REJECT

**测试命令:**
```
vpc
security-groups
```

**清理步骤:**
```bash
# 恢复安全组规则
aws ec2 authorize-security-group-ingress \
  --group-id $SG_ID \
  --protocol tcp \
  --port 22 \
  --cidr 0.0.0.0/0
```

---

### 场景 4.2: Route53 DNS 解析故障
**测试方法:**

**注入故障步骤:**
```bash
# 1. 列出 hosted zones
aws route53 list-hosted-zones

# 2. 修改记录指向错误 IP (测试用)
aws route53 change-resource-record-sets \
  --hosted-zone-id <zone-id> \
  --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "test.example.com",
        "Type": "A",
        "TTL": 60,
        "ResourceRecords": [{"Value": "127.0.0.1"}]
      }
    }]
  }'
```

**预期检测:**
- DNS 解析返回错误 IP
- 应用无法访问

---

## 测试场景 5: DynamoDB 故障

### 场景 5.1: DynamoDB 读写容量限制
**目标表:** `FrrSensor` (已有活跃告警)

**当前状态:**
```
告警: TargetTracking-table/FrrSensor-AlarmLow-xxx (ALARM)
原因: ConsumedReadCapacityUnits / ConsumedWriteCapacityUnits 低于阈值
```

**注入故障步骤:**
```bash
# 1. 降低预置容量
aws dynamodb update-table \
  --table-name FrrSensor \
  --provisioned-throughput ReadCapacityUnits=1,WriteCapacityUnits=1

# 2. 发送大量读写请求
python3 << 'EOF'
import boto3
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('FrrSensor')
for i in range(1000):
    table.put_item(Item={'id': f'test-{i}', 'data': 'x' * 1000})
EOF
```

**预期检测:**
- ProvisionedThroughputExceededException
- ThrottledRequests 指标增加

**测试命令:**
```
dynamodb
dynamodb health
```

---

### 场景 5.2: DynamoDB 表不可用
**模拟场景:** 删除 GSI 导致查询失败

```bash
# 删除 GSI (如果存在)
aws dynamodb update-table \
  --table-name Music \
  --global-secondary-index-updates '[{"Delete":{"IndexName":"AlbumTitle-index"}}]'
```

---

## 测试场景 6: CloudWatch 告警级联

### 场景 6.1: 多服务故障组合测试

**步骤:**
1. 同时触发 EC2 CPU 高 + Lambda 超时
2. 观察告警级联效应
3. 验证 RCA 分析能力

```bash
# 并行执行多个故障注入
# Terminal 1: EC2 CPU
ssh ubuntu@<ec2-ip> "stress --cpu 4 --timeout 300"

# Terminal 2: Lambda 超时
aws lambda invoke --function-name SensativeAPI \
  --payload '{"delay": 30000}' response.json
```

**测试命令:**
```
health
scan
sop suggest multiple failures
```

---

## 测试执行清单

| # | 场景 | 目标资源 | 风险级别 | 预计时间 |
|---|------|---------|---------|---------|
| 1.1 | EC2 高 CPU | i-080ab08eefa16b539 | 低 | 5 分钟 |
| 1.2 | EC2 内存不足 | i-0e6da7fadd619d0a7 | 中 | 5 分钟 |
| 1.3 | EC2 磁盘满 | i-080ab08eefa16b539 | 低 | 5 分钟 |
| 2.1 | Lambda 超时 | pet-store-PetStoreFunction | 低 | 3 分钟 |
| 2.2 | Lambda OOM | SensativeAPI | 低 | 3 分钟 |
| 3.1 | ALB 后端不健康 | alb-lambda-pets | 中 | 5 分钟 |
| 3.2 | ALB 5xx 错误 | ASG-Nginx-ALB | 中 | 5 分钟 |
| 4.1 | 安全组变更 | sg-05b91c933f703cc72 | 高 | 5 分钟 |
| 4.2 | DNS 解析故障 | Route53 | 高 | 5 分钟 |
| 5.1 | DynamoDB 限流 | FrrSensor | 低 | 5 分钟 |
| 6.1 | 多服务组合 | 多个 | 中 | 10 分钟 |

---

## 注意事项

⚠️ **重要提醒:**
1. 测试前备份所有配置
2. 避免在生产环境直接执行
3. 每个测试后执行清理步骤
4. 建议在测试时段执行 (非业务高峰)
5. 保持监控窗口打开

📋 **测试前准备:**
- [ ] 确认目标资源可测试
- [ ] 准备回滚脚本
- [ ] 通知相关团队
- [ ] 开启 CloudWatch 监控

---

*文档生成: AIOps Team @ 2026-02-10*
