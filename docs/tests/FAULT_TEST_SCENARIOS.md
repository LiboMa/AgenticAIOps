# AWS 故障测试方案

基于真实 AWS 环境设计的故障测试场景和步骤。

## 环境概览

| 资源类型 | 数量 | 关键资源 |
|----------|------|----------|
| EC2 实例 | 14 (4 running) | jump-ab2-db-proxy, nacos-server |
| Lambda 函数 | 12 | pet-store, SensativeAPI, aiops-eks-operations |
| 负载均衡器 | 11 | alb-lambda-pets, ASG-Nginx-ALB |
| DynamoDB 表 | 4 | FrrSensor, Music |
| EKS 集群 | 1 | testing-cluster |
| 当前告警 | 6 | DynamoDB 容量相关 |

---

## 测试场景 1: EC2 实例故障

### 场景 1.1: EC2 CPU 飙高

**目标实例**: `jump-ab2-db-proxy` (i-0e6da7fadd619d0a7, m5.xlarge, running)

**故障注入**:
```bash
# SSH 登录后执行 (模拟 CPU 压力)
stress-ng --cpu 4 --timeout 300s
```

**测试步骤**:
1. 记录基线 CPU 指标
   ```bash
   aws cloudwatch get-metric-statistics \
     --namespace AWS/EC2 \
     --metric-name CPUUtilization \
     --dimensions Name=InstanceId,Value=i-0e6da7fadd619d0a7 \
     --start-time $(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%SZ) \
     --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
     --period 60 --statistics Average
   ```

2. 执行故障注入 (CPU 压力)

3. 使用 Chat 命令检测
   ```
   ec2 health
   health check
   ```

4. 验证系统检测到异常

5. 停止故障注入，验证恢复

**预期结果**:
- Detect Agent 识别 CPU 高使用率
- 匹配 Pattern: ec2-high-cpu
- 推荐 SOP: sop-ec2-high-cpu

---

### 场景 1.2: EC2 实例不可达

**目标实例**: `ec2-az-1` (i-050f8d0637b5ea512, 当前 stopped)

**测试步骤**:
1. 启动实例
   ```
   ec2 start i-050f8d0637b5ea512
   ```

2. 等待实例运行

3. 修改 Security Group 阻断连接
   ```bash
   # 记录当前 SG
   aws ec2 describe-instances --instance-ids i-050f8d0637b5ea512 \
     --query 'Reservations[0].Instances[0].SecurityGroups'
   
   # 创建空 SG (无入站规则)
   aws ec2 create-security-group --group-name test-block-sg \
     --description "Test - block all traffic" --vpc-id <vpc-id>
   
   # 应用空 SG (模拟网络隔离)
   aws ec2 modify-instance-attribute --instance-id i-050f8d0637b5ea512 \
     --groups <empty-sg-id>
   ```

4. 使用系统检测
   ```
   health check
   ec2 health
   ```

5. 恢复原 Security Group

**预期结果**:
- 系统检测到实例不可达
- RCA Agent 识别 Security Group 变更
- 推荐恢复操作

---

## 测试场景 2: Lambda 函数故障

### 场景 2.1: Lambda 调用超时

**目标函数**: `pet-store-PetStoreFunction-YwXsum9ltfg7` (java17, 1512MB)

**测试步骤**:
1. 获取当前配置
   ```bash
   aws lambda get-function-configuration \
     --function-name pet-store-PetStoreFunction-YwXsum9ltfg7
   ```

2. 临时降低超时 (模拟超时故障)
   ```bash
   aws lambda update-function-configuration \
     --function-name pet-store-PetStoreFunction-YwXsum9ltfg7 \
     --timeout 1
   ```

3. 触发函数调用
   ```
   lambda invoke pet-store-PetStoreFunction-YwXsum9ltfg7
   ```

4. 检查错误
   ```
   lambda health
   ```

5. 恢复原超时配置

**预期结果**:
- 函数调用超时错误
- 系统记录错误 Pattern
- 推荐增加超时或优化代码

---

### 场景 2.2: Lambda 内存不足

**目标函数**: `SensativeAPI` (python3.13, 128MB)

**测试步骤**:
1. 记录当前配置
2. 创建测试 payload (大数据量)
3. 调用函数触发 OOM
4. 检查 CloudWatch Logs
5. 使用系统分析
   ```
   lambda health
   kb search "lambda memory"
   ```

**预期结果**:
- 检测到内存不足错误
- 推荐增加内存配置

---

## 测试场景 3: 负载均衡器故障

### 场景 3.1: ALB 后端健康检查失败

**目标 ALB**: `alb-lambda-pets`

**测试步骤**:
1. 获取 Target Group
   ```bash
   aws elbv2 describe-target-groups \
     --load-balancer-arn <alb-arn> \
     --query 'TargetGroups[*].[TargetGroupArn,TargetGroupName]'
   ```

2. 检查当前健康状态
   ```bash
   aws elbv2 describe-target-health --target-group-arn <tg-arn>
   ```

3. 修改健康检查路径 (模拟失败)
   ```bash
   aws elbv2 modify-target-group \
     --target-group-arn <tg-arn> \
     --health-check-path /nonexistent-path
   ```

4. 等待健康检查失败

5. 使用系统检测
   ```
   elb
   elb health
   health check
   ```

6. 恢复正确的健康检查路径

**预期结果**:
- 检测到后端不健康
- 分析原因: 健康检查配置错误
- 推荐修复健康检查路径

---

## 测试场景 4: DynamoDB 故障

### 场景 4.1: DynamoDB 读写容量告警

**目标表**: `FrrSensor` (当前已有 ALARM)

**当前告警状态**:
```
TargetTracking-table/FrrSensor-AlarmLow (ConsumedWriteCapacityUnits) - ALARM
TargetTracking-table/FrrSensor-AlarmLow (ConsumedReadCapacityUnits) - ALARM
```

**测试步骤**:
1. 检查当前告警
   ```
   health check
   dynamodb health
   ```

2. 分析告警详情
   ```bash
   aws cloudwatch describe-alarms \
     --alarm-names "TargetTracking-table/FrrSensor-AlarmLow-0a11cf6d-c294-4127-8b2b-d8a70becc609"
   ```

3. 验证系统检测
   ```
   kb search "dynamodb capacity"
   sop suggest dynamodb alarm
   ```

**预期结果**:
- 系统识别现有告警
- 分析容量使用模式
- 推荐调整容量或启用自动扩展

---

### 场景 4.2: DynamoDB 节流 (Throttling)

**目标表**: `Music`

**测试步骤**:
1. 获取当前容量
   ```bash
   aws dynamodb describe-table --table-name Music \
     --query 'Table.ProvisionedThroughput'
   ```

2. 临时降低 WCU (模拟节流)
   ```bash
   aws dynamodb update-table --table-name Music \
     --provisioned-throughput ReadCapacityUnits=1,WriteCapacityUnits=1
   ```

3. 执行大量写入操作 (触发节流)
   ```python
   import boto3
   dynamodb = boto3.resource('dynamodb')
   table = dynamodb.Table('Music')
   for i in range(100):
       table.put_item(Item={'Artist': f'Test-{i}', 'SongTitle': f'Song-{i}'})
   ```

4. 检查节流指标
   ```bash
   aws cloudwatch get-metric-statistics \
     --namespace AWS/DynamoDB \
     --metric-name ThrottledRequests \
     --dimensions Name=TableName,Value=Music \
     --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%SZ) \
     --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
     --period 60 --statistics Sum
   ```

5. 使用系统分析
   ```
   dynamodb health
   health check
   ```

6. 恢复容量

**预期结果**:
- 检测到 ThrottledRequests
- Pattern: dynamodb-throttling
- 推荐增加容量或优化访问模式

---

## 测试场景 5: EKS 集群故障

### 场景 5.1: EKS Pod 资源不足

**目标集群**: `testing-cluster`

**测试步骤**:
1. 连接集群
   ```bash
   aws eks update-kubeconfig --name testing-cluster
   ```

2. 检查当前 Pod 状态
   ```bash
   kubectl get pods --all-namespaces | grep -v Running
   ```

3. 部署资源密集型测试 Pod
   ```yaml
   # stress-test.yaml
   apiVersion: v1
   kind: Pod
   metadata:
     name: stress-test
   spec:
     containers:
     - name: stress
       image: polinux/stress
       resources:
         requests:
           memory: "10Gi"
           cpu: "4"
       command: ["stress"]
       args: ["--vm", "1", "--vm-bytes", "8G", "--timeout", "300s"]
   ```

4. 观察 Pod 状态
   ```bash
   kubectl describe pod stress-test
   kubectl get events --sort-by='.lastTimestamp'
   ```

5. 使用系统检测
   ```
   eks health
   health check
   ```

6. 清理测试 Pod

**预期结果**:
- 检测到资源不足事件
- 分析节点容量
- 推荐扩展节点或调整资源请求

---

## 测试场景 6: 多服务级联故障

### 场景 6.1: ALB → Lambda → DynamoDB 链路故障

**故障链**: `alb-lambda-pets` → `pet-store-PetStoreFunction` → `Music` 表

**测试步骤**:
1. 检查完整链路基线
   ```
   elb
   lambda
   dynamodb
   ```

2. 在 DynamoDB 层注入故障 (降低容量)

3. 触发 ALB 请求

4. 观察级联效应:
   - Lambda 超时
   - ALB 5xx 错误增加

5. 使用系统追踪
   ```
   health check
   kb search "timeout"
   ```

**预期结果**:
- 系统识别根因在 DynamoDB
- RCA Agent 追踪完整调用链
- 提供端到端分析报告

---

## 测试执行计划

| 序号 | 场景 | 风险级别 | 预计时间 | 前置条件 |
|------|------|----------|----------|----------|
| 1 | EC2 CPU 压力 | 低 | 15 min | 实例运行中 |
| 2 | EC2 网络隔离 | 中 | 20 min | 测试实例 |
| 3 | Lambda 超时 | 低 | 10 min | 可恢复配置 |
| 4 | Lambda OOM | 低 | 10 min | 测试函数 |
| 5 | ALB 健康检查 | 中 | 15 min | 测试 TG |
| 6 | DynamoDB 告警 | 低 | 10 min | 现有告警 |
| 7 | DynamoDB 节流 | 中 | 20 min | 可恢复容量 |
| 8 | EKS Pod 资源 | 中 | 20 min | 集群访问 |
| 9 | 级联故障 | 高 | 30 min | 完整链路 |

**总预计时间**: ~2.5 小时

---

## 验证清单

每个测试场景需验证:

- [ ] 故障成功注入
- [ ] Collect Agent 收集到异常数据
- [ ] Pattern Agent 识别并分类模式
- [ ] Detect Agent 触发告警
- [ ] RCA Agent 分析根因
- [ ] SOP 推荐正确
- [ ] 故障恢复后系统状态正常
- [ ] Pattern 保存到向量库 (OpenSearch)

---

**作者**: Architect
**日期**: 2026-02-10
**版本**: 1.0
