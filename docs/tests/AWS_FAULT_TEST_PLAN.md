# AWS 故障测试计划

**文档版本:** v1.0
**创建日期:** 2026-02-10
**环境:** AWS ap-southeast-1
**账号:** 533267047935

---

## 1. 测试环境概述

### 1.1 当前资源清单

| 资源类型 | 数量 | 详情 |
|---------|------|------|
| EC2 实例 | 14 | 4 running, 10 stopped |
| EKS 集群 | 1 | testing-cluster |
| Lambda 函数 | 12 | 含 pet-store, SensativeAPI 等 |
| 负载均衡器 | 11 | 7 ALB, 3 NLB, 1 GWLB |
| DynamoDB 表 | 4 | FrrSensor, Music 等 |
| VPC | 6 | 含 project-vpc, Appliance-VPC 等 |
| S3 桶 | 50+ | 含 agentic-aiops-kb 等 |

### 1.2 Running EC2 实例

| Instance ID | Name | Type | 用途 |
|-------------|------|------|------|
| i-0e6da7fadd619d0a7 | jump-ab2-db-proxy | m5.xlarge | 跳板机/代理 |
| i-019b2cab1bb30c430 | (unnamed) | r6i.metal | 高性能计算 |
| i-080ab08eefa16b539 | mbot-sg-1 | m6i.xlarge | AgenticAIOps 服务器 |
| i-089ef0b7795744434 | (unnamed) | c6g.large | ARM 计算 |

### 1.3 负载均衡器

| 名称 | 类型 | 状态 |
|------|------|------|
| alb-lambda-pets | Application | active |
| alb-nacos-demo | Application | active |
| vpca-alb-protected | Application | active |
| sensative-api-lb | Application | active |
| ASG-Nginx-ALB | Application | active |
| dify-test | Application | active |
| cloudreve-lb | Application | active |
| nlb-for-db-test | Network | active |
| dify-test-nlb | Network | active |
| GWLB-Fortinet-01 | Gateway | active |

---

## 2. 故障测试场景

### 2.1 测试场景 1: EC2 高 CPU 故障

**目的:** 验证系统对 EC2 CPU 异常的检测和响应能力

**目标资源:**
- 实例: `i-080ab08eefa16b539` (mbot-sg-1)
- 类型: m6i.xlarge (4 vCPU)

**测试步骤:**

| 步骤 | 操作 | 命令/方法 | 预期结果 |
|------|------|----------|---------|
| 1 | 基线检查 | `ec2 health` | 记录当前 CPU 基线 |
| 2 | 查看指标 | `ec2 metrics i-080ab08eefa16b539` | 确认 CPU < 30% |
| 3 | 注入故障 | SSH: `stress --cpu 4 --timeout 300` | CPU 升至 >90% |
| 4 | 检测异常 | `anomaly` | 系统检测到 CPU 异常 |
| 5 | 健康检查 | `ec2 health` | 显示 CPU 告警 |
| 6 | 执行 SOP | `sop run sop-ec2-high-cpu` | 按步骤排查 |
| 7 | 恢复验证 | 等待 stress 结束后 `ec2 health` | CPU 恢复正常 |

**成功标准:**
- [ ] 系统在 5 分钟内检测到 CPU 异常
- [ ] SOP 推荐正确
- [ ] 恢复后健康检查通过

---

### 2.2 测试场景 2: EC2 实例停止故障

**目的:** 验证系统对 EC2 实例状态变化的检测能力

**目标资源:**
- 实例: `i-0e6da7fadd619d0a7` (jump-ab2-db-proxy)
- 类型: m5.xlarge

**测试步骤:**

| 步骤 | 操作 | 命令/方法 | 预期结果 |
|------|------|----------|---------|
| 1 | 基线检查 | `ec2 health` | 实例状态 running |
| 2 | 停止实例 | `ec2 stop i-0e6da7fadd619d0a7` | 实例开始停止 |
| 3 | 等待状态变更 | 等待 1-2 分钟 | 状态变为 stopped |
| 4 | 健康检查 | `ec2 health` | 检测到实例 stopped |
| 5 | 异常检测 | `anomaly` | 报告实例异常 |
| 6 | SOP 推荐 | `sop suggest ec2 stopped` | 推荐启动 SOP |
| 7 | 恢复实例 | `ec2 start i-0e6da7fadd619d0a7` | 实例开始启动 |
| 8 | 验证恢复 | `ec2 health` | 实例状态 running |

**成功标准:**
- [ ] 停止/启动操作成功执行
- [ ] 健康检查正确反映状态变化
- [ ] SOP 推荐相关

---

### 2.3 测试场景 3: Lambda 函数错误

**目的:** 验证系统对 Lambda 错误的检测和日志分析能力

**目标资源:**
- 函数: `SensativeAPI`
- Runtime: python3.13

**测试步骤:**

| 步骤 | 操作 | 命令/方法 | 预期结果 |
|------|------|----------|---------|
| 1 | 基线检查 | `lambda health` | 查看当前健康状态 |
| 2 | 查看日志 | `lambda logs SensativeAPI` | 查看近期日志 |
| 3 | 触发调用 | `lambda invoke SensativeAPI` | 调用函数 |
| 4 | 检查结果 | 查看调用响应 | 记录成功/失败 |
| 5 | 查看日志 | `lambda logs SensativeAPI` | 查看执行日志 |
| 6 | 健康检查 | `lambda health` | 检测错误率 |
| 7 | SOP 推荐 | `sop suggest lambda errors` | 推荐排查 SOP |

**成功标准:**
- [ ] Lambda 调用执行成功
- [ ] 日志正确显示
- [ ] 错误检测正常工作

---

### 2.4 测试场景 4: ALB 目标不健康

**目的:** 验证系统对负载均衡器健康状态的监控能力

**目标资源:**
- ALB: `alb-nacos-demo`
- 后端实例: `i-06b75135a2518cb05` (nacos-server)

**测试步骤:**

| 步骤 | 操作 | 命令/方法 | 预期结果 |
|------|------|----------|---------|
| 1 | 基线检查 | `elb health` | 查看当前 ELB 状态 |
| 2 | 启动后端 | `ec2 start i-06b75135a2518cb05` | 确保后端运行 |
| 3 | 检查目标健康 | `elb health` | 目标应为 healthy |
| 4 | 停止后端 | `ec2 stop i-06b75135a2518cb05` | 模拟后端故障 |
| 5 | 等待检测 | 等待 1-2 分钟 | 健康检查失败 |
| 6 | 健康检查 | `elb health` | 检测到 unhealthy targets |
| 7 | 异常检测 | `anomaly` | 报告 ELB 异常 |
| 8 | 恢复后端 | `ec2 start i-06b75135a2518cb05` | 恢复后端实例 |
| 9 | 验证恢复 | `elb health` | 目标恢复 healthy |

**成功标准:**
- [ ] ELB 健康检查正确反映后端状态
- [ ] unhealthy targets 被检测到
- [ ] 恢复后状态正确更新

---

### 2.5 测试场景 5: EKS Pod 故障

**目的:** 验证系统对 Kubernetes Pod 故障的检测能力

**目标资源:**
- 集群: `testing-cluster`
- 测试 Pod: `fault-test`

**测试步骤:**

| 步骤 | 操作 | 命令/方法 | 预期结果 |
|------|------|----------|---------|
| 1 | 基线检查 | `eks health` 或 `k8s pods` | 查看当前 Pod 状态 |
| 2 | 创建故障 Pod | `kubectl run fault-test --image=busybox -- /bin/sh -c "exit 1"` | Pod 开始创建 |
| 3 | 检查状态 | `kubectl get pods` | Pod 为 CrashLoopBackOff |
| 4 | 健康检查 | `eks health` | 检测到 Pod 异常 |
| 5 | 查看事件 | `kubectl describe pod fault-test` | 查看错误详情 |
| 6 | 清理 | `kubectl delete pod fault-test` | 删除测试 Pod |
| 7 | 验证恢复 | `eks health` | 无异常 Pod |

**成功标准:**
- [ ] CrashLoopBackOff 被正确检测
- [ ] 健康检查报告 Pod 异常
- [ ] 清理后状态恢复

---

### 2.6 测试场景 6: DynamoDB 节流

**目的:** 验证系统对 DynamoDB 性能问题的检测能力

**目标资源:**
- 表: `Music`

**测试步骤:**

| 步骤 | 操作 | 命令/方法 | 预期结果 |
|------|------|----------|---------|
| 1 | 基线检查 | `dynamodb health` | 查看当前状态 |
| 2 | 查看容量 | `dynamodb` | 查看表信息 |
| 3 | 生成负载 | 批量 scan 请求 | 触发节流 |
| 4 | 检查节流 | `dynamodb health` | 检测 ThrottledRequests |
| 5 | 异常检测 | `anomaly` | 报告节流异常 |

**成功标准:**
- [ ] 节流事件被检测到
- [ ] 建议增加容量

---

### 2.7 测试场景 7: 综合健康检查

**目的:** 验证系统全面健康检查能力

**测试步骤:**

| 步骤 | 操作 | 命令/方法 | 预期结果 |
|------|------|----------|---------|
| 1 | 全服务健康检查 | `health` | 显示所有服务状态 |
| 2 | 异常检测 | `anomaly` | 列出所有异常 |
| 3 | 全资源扫描 | `scan` | 扫描所有资源 |
| 4 | 知识库搜索 | `kb search high cpu` | 搜索相关知识 |
| 5 | SOP 列表 | `sop list` | 查看可用 SOP |

**成功标准:**
- [ ] 所有命令正常执行
- [ ] 结果准确反映环境状态

---

## 3. 测试执行计划

### 3.1 推荐执行顺序

```
1. 测试 7: 综合健康检查 (建立基线)
2. 测试 1: EC2 高 CPU (低风险)
3. 测试 3: Lambda 错误 (低风险)
4. 测试 5: EKS Pod 故障 (中风险)
5. 测试 2: EC2 停止 (中风险 - 注意选择非关键实例)
6. 测试 4: ALB 不健康 (中风险 - 注意业务影响)
7. 测试 6: DynamoDB 节流 (低风险)
```

### 3.2 风险评估

| 测试 | 风险等级 | 业务影响 | 注意事项 |
|------|---------|---------|---------|
| 测试 1 | 低 | 无 | mbot-sg-1 可承受高 CPU |
| 测试 2 | 中 | 可能影响代理服务 | 确认无依赖后执行 |
| 测试 3 | 低 | 无 | Lambda 调用隔离 |
| 测试 4 | 中 | 可能影响 Nacos | 确认无业务使用 |
| 测试 5 | 低 | 无 | 测试 Pod 隔离 |
| 测试 6 | 低 | 无 | 读操作为主 |
| 测试 7 | 无 | 无 | 只读操作 |

### 3.3 回滚计划

每个测试都包含恢复步骤。如遇紧急情况：

```bash
# EC2 紧急恢复
aws ec2 start-instances --instance-ids <instance-id>

# EKS Pod 清理
kubectl delete pod fault-test --force

# 停止 stress 测试
pkill stress
```

---

## 4. 测试结果记录模板

### 测试记录表

| 项目 | 内容 |
|------|------|
| 测试编号 | |
| 测试日期 | |
| 测试人员 | |
| 开始时间 | |
| 结束时间 | |
| 测试结果 | ✅ 通过 / ❌ 失败 |
| 检测延迟 | |
| 问题发现 | |
| 改进建议 | |

---

## 5. 附录

### 5.1 常用命令参考

```bash
# 健康检查
ec2 health
rds health
lambda health
elb health
eks health
vpc health
health          # 全服务
anomaly         # 异常检测

# 资源查看
ec2
lambda
s3
rds
elb
vpc
scan            # 全资源扫描

# 操作
ec2 start <instance-id>
ec2 stop <instance-id>
ec2 reboot <instance-id>
lambda invoke <function-name>

# SOP
sop list
sop show <sop-id>
sop suggest <service> <keywords>
sop run <sop-id>

# 知识库
kb stats
kb search <query>
```

### 5.2 联系方式

- 技术支持: AgenticAIOps Team
- 紧急联系: Ma Ronnie

---

**文档结束**
