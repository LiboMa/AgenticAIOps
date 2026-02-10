# AWS 故障测试方案 - 基于真实环境数据

## 测试环境概览

| 资源类型 | 数量 | 详情 |
|---------|------|------|
| EC2 实例 | 14 (4 running) | m5.xlarge, r6i.metal, m6i.xlarge, c6g.large |
| Lambda 函数 | 12+ | Python, Java |
| DynamoDB 表 | 4 | FrrSensor, Music, active-number-server, ice-json-poc |
| EKS 集群 | 1 | testing-cluster |
| S3 桶 | 10+ | 包含 aiops-knowledge-base |
| CloudWatch 告警 | 6 (ALARM) | DynamoDB TargetTracking |

---

## 测试场景 1: EC2 高 CPU 故障

### 目标实例
- **Instance ID**: `i-0e6da7fadd619d0a7` (jump-ab2-db-proxy)
- **Type**: m5.xlarge
- **IP**: 10.0.1.147

### 测试步骤

```bash
# Step 1: SSH 到目标实例
ssh -i <key.pem> ec2-user@10.0.1.147

# Step 2: 模拟 CPU 高负载 (stress 工具)
sudo yum install -y stress
stress --cpu 4 --timeout 300  # 4核 CPU 压力，持续5分钟

# Step 3: 使用 AIOps 平台检测
curl -X POST http://10.0.1.120:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "EC2 health"}'

# Step 4: 查看 CloudWatch 指标
aws cloudwatch get-metric-statistics \
  --namespace AWS/EC2 \
  --metric-name CPUUtilization \
  --dimensions Name=InstanceId,Value=i-0e6da7fadd619d0a7 \
  --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 \
  --statistics Average

# Step 5: 使用 SOP 处理
curl -X POST http://10.0.1.120:8000/api/chat \
  -d '{"message": "sop suggest ec2 high cpu"}'
```

### 预期结果
- CPU 使用率 > 90%
- AIOps 检测到异常
- SOP 推荐: `sop-ec2-high-cpu`

---

## 测试场景 2: Lambda 函数错误

### 目标函数
- **Function**: `SensativeAPI`
- **Runtime**: python3.13
- **Memory**: 128 MB

### 测试步骤

```bash
# Step 1: 触发 Lambda 执行错误 (构造错误 payload)
aws lambda invoke \
  --function-name SensativeAPI \
  --payload '{"invalid": "data", "trigger_error": true}' \
  --cli-binary-format raw-in-base64-out \
  response.json

# Step 2: 查看执行日志
aws logs tail /aws/lambda/SensativeAPI --since 5m

# Step 3: 使用 AIOps 检测 Lambda 健康
curl -X POST http://10.0.1.120:8000/api/chat \
  -d '{"message": "Lambda health"}'

# Step 4: 查看错误日志
curl -X POST http://10.0.1.120:8000/api/chat \
  -d '{"message": "Lambda error logs SensativeAPI"}'

# Step 5: 使用 SOP 处理
curl -X POST http://10.0.1.120:8000/api/chat \
  -d '{"message": "sop suggest lambda errors"}'
```

### 预期结果
- Lambda 执行失败
- CloudWatch Logs 记录错误
- SOP 推荐: `sop-lambda-errors`

---

## 测试场景 3: DynamoDB 节流 (Throttling)

### 目标表
- **Table**: `FrrSensor`
- **当前状态**: ALARM (ConsumedReadCapacityUnits)

### 测试步骤

```bash
# Step 1: 生成大量读取请求 (模拟节流)
python3 << 'EOF'
import boto3
import concurrent.futures

dynamodb = boto3.resource('dynamodb', region_name='ap-southeast-1')
table = dynamodb.Table('FrrSensor')

def read_item(i):
    try:
        response = table.scan(Limit=100)
        return response.get('Count', 0)
    except Exception as e:
        return str(e)

# 并发100个请求
with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
    results = list(executor.map(read_item, range(500)))
    errors = [r for r in results if isinstance(r, str) and 'Throttl' in r]
    print(f"Total requests: 500, Throttled: {len(errors)}")
EOF

# Step 2: 检查 CloudWatch 告警状态
aws cloudwatch describe-alarms \
  --alarm-name-prefix "TargetTracking-table/FrrSensor" \
  --query 'MetricAlarms[*].[AlarmName,StateValue]' \
  --output table

# Step 3: 使用 AIOps 检测
curl -X POST http://10.0.1.120:8000/api/chat \
  -d '{"message": "dynamodb"}'

# Step 4: 查看知识库推荐
curl -X POST http://10.0.1.120:8000/api/chat \
  -d '{"message": "kb search dynamodb throttle"}'
```

### 预期结果
- DynamoDB 出现 ProvisionedThroughputExceededException
- CloudWatch 告警触发
- AIOps 检测到 DynamoDB 异常

---

## 测试场景 4: EKS 集群 Pod 故障

### 目标集群
- **Cluster**: `testing-cluster`

### 测试步骤

```bash
# Step 1: 配置 kubectl
aws eks update-kubeconfig --name testing-cluster --region ap-southeast-1

# Step 2: 部署一个故障 Pod
kubectl apply -f - << 'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: crash-test-pod
  namespace: default
spec:
  containers:
  - name: crash-container
    image: busybox
    command: ['sh', '-c', 'exit 1']  # 立即退出，触发 CrashLoopBackOff
  restartPolicy: Always
EOF

# Step 3: 等待 Pod 进入 CrashLoopBackOff
sleep 60
kubectl get pods crash-test-pod

# Step 4: 使用 AIOps 检测 EKS 健康
curl -X POST http://10.0.1.120:8000/api/chat \
  -d '{"message": "EKS health"}'

# Step 5: 清理测试 Pod
kubectl delete pod crash-test-pod
```

### 预期结果
- Pod 状态: CrashLoopBackOff
- AIOps 检测到 EKS 集群中的异常 Pod

---

## 测试场景 5: S3 访问权限故障

### 目标桶
- **Bucket**: `agentic-aiops-kb-1769960769`

### 测试步骤

```bash
# Step 1: 创建临时限制策略 (模拟权限问题)
aws s3api put-bucket-policy --bucket agentic-aiops-kb-1769960769 --policy '{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Deny",
    "Principal": "*",
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::agentic-aiops-kb-1769960769/test-deny/*"
  }]
}'

# Step 2: 尝试访问被拒绝的对象
aws s3 cp s3://agentic-aiops-kb-1769960769/test-deny/test.txt ./test.txt 2>&1

# Step 3: 使用 AIOps 检测 S3 健康
curl -X POST http://10.0.1.120:8000/api/chat \
  -d '{"message": "S3 health"}'

# Step 4: 恢复正常策略
aws s3api delete-bucket-policy --bucket agentic-aiops-kb-1769960769
```

### 预期结果
- S3 GetObject 操作被拒绝
- AIOps 检测到 S3 安全问题

---

## 测试场景 6: 网络连接故障

### 目标
- **VPC 内 EC2 实例网络测试**

### 测试步骤

```bash
# Step 1: 检查当前安全组规则
aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=*mbot*" \
  --query 'SecurityGroups[*].[GroupId,GroupName]' \
  --output table

# Step 2: 创建测试安全组 (阻断所有出站)
SG_ID=$(aws ec2 create-security-group \
  --group-name test-network-fault \
  --description "Test network fault" \
  --vpc-id vpc-0e52b16f067c1c8c0 \
  --output text --query 'GroupId')

# Step 3: 移除默认出站规则
aws ec2 revoke-security-group-egress \
  --group-id $SG_ID \
  --ip-permissions '[{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]'

# Step 4: 使用 AIOps 检测 VPC 健康
curl -X POST http://10.0.1.120:8000/api/chat \
  -d '{"message": "vpc health"}'

# Step 5: 清理测试安全组
aws ec2 delete-security-group --group-id $SG_ID
```

### 预期结果
- 网络连接测试失败
- AIOps 检测到 VPC 配置问题

---

## 测试场景 7: CloudWatch 告警测试

### 目标
- 创建自定义告警并触发

### 测试步骤

```bash
# Step 1: 创建测试告警 (低阈值，易触发)
aws cloudwatch put-metric-alarm \
  --alarm-name "AIOps-Test-CPU-Alarm" \
  --metric-name CPUUtilization \
  --namespace AWS/EC2 \
  --statistic Average \
  --period 60 \
  --threshold 1 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=InstanceId,Value=i-080ab08eefa16b539 \
  --evaluation-periods 1 \
  --alarm-description "AIOps test alarm for CPU"

# Step 2: 等待告警触发
sleep 120
aws cloudwatch describe-alarms \
  --alarm-names "AIOps-Test-CPU-Alarm" \
  --query 'MetricAlarms[*].[AlarmName,StateValue]'

# Step 3: 使用 AIOps 发送告警通知
curl -X POST http://10.0.1.120:8000/api/chat \
  -d '{"message": "test notification"}'

# Step 4: 清理测试告警
aws cloudwatch delete-alarms --alarm-names "AIOps-Test-CPU-Alarm"
```

### 预期结果
- CloudWatch 告警进入 ALARM 状态
- AIOps 通知系统触发

---

## 测试执行清单

| 场景 | 风险级别 | 预计时间 | 是否需要清理 |
|------|---------|---------|-------------|
| EC2 高 CPU | 低 | 10分钟 | 自动恢复 |
| Lambda 错误 | 低 | 5分钟 | 无需 |
| DynamoDB 节流 | 中 | 10分钟 | 无需 |
| EKS Pod 故障 | 低 | 5分钟 | 需要 |
| S3 权限 | 低 | 5分钟 | 需要 |
| 网络故障 | 中 | 10分钟 | 需要 |
| CloudWatch 告警 | 低 | 5分钟 | 需要 |

---

## 自动化测试脚本

```bash
#!/bin/bash
# run_fault_tests.sh - AIOps 故障测试自动化脚本

API_URL="http://10.0.1.120:8000/api/chat"

echo "=========================================="
echo "  AIOps 故障测试开始"
echo "=========================================="

# Test 1: EC2 Health Check
echo -e "\n[Test 1] EC2 健康检查..."
curl -s -X POST $API_URL -H "Content-Type: application/json" \
  -d '{"message": "EC2 health"}' | jq -r '.response[:200]'

# Test 2: Lambda Health Check
echo -e "\n[Test 2] Lambda 健康检查..."
curl -s -X POST $API_URL -H "Content-Type: application/json" \
  -d '{"message": "Lambda health"}' | jq -r '.response[:200]'

# Test 3: DynamoDB Check
echo -e "\n[Test 3] DynamoDB 检查..."
curl -s -X POST $API_URL -H "Content-Type: application/json" \
  -d '{"message": "dynamodb"}' | jq -r '.response[:200]'

# Test 4: SOP Suggestion
echo -e "\n[Test 4] SOP 推荐..."
curl -s -X POST $API_URL -H "Content-Type: application/json" \
  -d '{"message": "sop suggest ec2 high cpu"}' | jq -r '.response[:200]'

# Test 5: Knowledge Search
echo -e "\n[Test 5] 知识库搜索..."
curl -s -X POST $API_URL -H "Content-Type: application/json" \
  -d '{"message": "kb search timeout error"}' | jq -r '.response[:200]'

# Test 6: Full Health Check
echo -e "\n[Test 6] 全面健康检查..."
curl -s -X POST $API_URL -H "Content-Type: application/json" \
  -d '{"message": "health"}' | jq -r '.response[:500]'

echo -e "\n=========================================="
echo "  测试完成"
echo "=========================================="
```

---

## 注意事项

1. **生产环境风险**: 部分测试可能影响生产服务，建议在测试窗口执行
2. **资源清理**: 测试后务必清理临时创建的资源
3. **监控**: 测试期间持续监控 CloudWatch 和 AIOps 平台
4. **回滚计划**: 每个测试都有对应的回滚/清理步骤
