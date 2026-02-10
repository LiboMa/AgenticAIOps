# AWS 故障测试计划

**版本:** v1.0  
**日期:** 2026-02-10  
**作者:** Tester (AgenticAIOps Team)  
**环境:** ap-southeast-1  

---

## 1. 测试环境概览

### 1.1 AWS 资源清单

| 服务 | 数量 | 状态 |
|------|------|------|
| EC2 Instances | 14 | 4 running, 10 stopped |
| Lambda Functions | 12 | 1 issue detected |
| Load Balancers | 11 | All active |
| VPCs | 6 | Available |
| S3 Buckets | 20 | No public |
| DynamoDB Tables | 4 | Active |

### 1.2 当前已知问题

```
发现 11 个问题:
├── nacos-server (i-06b75135a2518cb05): stopped
├── ec2-az2 (i-0f963ef9e36d78568): stopped
├── selectDB-core-1 (i-02e3953e63985c3af): stopped
├── selectDB-manager (i-06589ea880492f29c): stopped
├── selectDB-core-2 (i-037cb6474a373dfff): stopped
├── ec2-az-1 (i-050f8d0637b5ea512): stopped
├── ec2-az-3 (i-082ac9eb994608b1d): stopped
├── nexus-ai-workshop (i-03ea4f7144326c761): stopped
├── win-server-demo-1 (i-0edf256e7d04e4b77): stopped
├── win-session-demo-4 (i-03c731a1d57051b3c): stopped
└── Lambda: 1 function issue
```

---

## 2. 测试用例

### 2.1 TC-001: EC2 实例故障模拟

**优先级:** P0  
**风险等级:** 中  
**预计时间:** 10 分钟  

**目标资源:**
- 实例: `jump-ab2-db-proxy` (i-0e6da7fadd619d0a7)
- 类型: m5.xlarge
- 状态: running
- IP: 10.0.1.147

**测试步骤:**

| 步骤 | 操作 | Chat 命令 | 预期结果 |
|------|------|-----------|----------|
| 1 | 记录基线状态 | `ec2 health` | 记录当前健康状态 |
| 2 | 模拟故障-停止实例 | `ec2 stop i-0e6da7fadd619d0a7` | 实例状态变为 stopping |
| 3 | 检测故障 | `ec2 health` | 检测到实例 stopped 异常 |
| 4 | 异常检测 | `anomaly` | 发现 EC2 异常 |
| 5 | 查询 SOP | `sop suggest ec2 stopped` | 推荐相关 SOP |
| 6 | 恢复服务 | `ec2 start i-0e6da7fadd619d0a7` | 实例状态变为 running |
| 7 | 验证恢复 | `ec2 health` | 确认恢复正常 |

**验证点:**
- [ ] 故障检测延迟 < 30 秒
- [ ] SOP 推荐准确
- [ ] 恢复操作成功

---

### 2.2 TC-002: Lambda 函数错误排查

**优先级:** P0  
**风险等级:** 低  
**预计时间:** 15 分钟  

**目标资源:**
- 函数: `SensativeAPI`
- Runtime: python3.13
- Memory: 128MB
- Timeout: 3s

**测试步骤:**

| 步骤 | 操作 | Chat 命令 | 预期结果 |
|------|------|-----------|----------|
| 1 | 查看健康状态 | `lambda health` | 显示 Lambda 健康状态 |
| 2 | 查看函数日志 | `lambda logs SensativeAPI` | 显示最近日志 |
| 3 | 触发函数执行 | `lambda invoke SensativeAPI` | 执行函数 |
| 4 | 检查执行结果 | `lambda logs SensativeAPI` | 查看执行结果/错误 |
| 5 | 查询 SOP | `sop suggest lambda errors` | 推荐 Lambda 错误排查 SOP |
| 6 | 执行 SOP | `sop show sop-lambda-errors` | 显示排查步骤 |

**验证点:**
- [ ] 日志查询正常
- [ ] 函数调用成功/失败原因清晰
- [ ] SOP 推荐相关

---

### 2.3 TC-003: 负载均衡器健康检查失败

**优先级:** P1  
**风险等级:** 中  
**预计时间:** 15 分钟  

**目标资源:**
- ALB: `alb-nacos-demo`
- 后端实例: `nacos-server` (i-06b75135a2518cb05) - 当前 stopped

**测试步骤:**

| 步骤 | 操作 | Chat 命令 | 预期结果 |
|------|------|-----------|----------|
| 1 | 查看 ELB 状态 | `elb health` | 显示所有 ELB 健康状态 |
| 2 | 启动后端实例 | `ec2 start i-06b75135a2518cb05` | 启动 nacos-server |
| 3 | 等待 Target 健康 | 等待 60 秒 | Target 变为 healthy |
| 4 | 验证 ELB 健康 | `elb health` | alb-nacos-demo 所有 targets healthy |
| 5 | 模拟故障-停止后端 | `ec2 stop i-06b75135a2518cb05` | 停止后端实例 |
| 6 | 检测 unhealthy | `elb health` | 检测到 unhealthy targets |
| 7 | 恢复并验证 | `ec2 start i-06b75135a2518cb05` | 恢复正常 |

**验证点:**
- [ ] ELB 健康检查状态准确
- [ ] Target 状态变化能被检测
- [ ] 故障恢复流程完整

---

### 2.4 TC-004: VPC 网络故障检测

**优先级:** P1  
**风险等级:** 低  
**预计时间:** 10 分钟  

**目标资源:**
- VPC: `project-vpc` (vpc-028fe79b3785c1aba)
- CIDR: 10.0.0.0/16

**测试步骤:**

| 步骤 | 操作 | Chat 命令 | 预期结果 |
|------|------|-----------|----------|
| 1 | 查看 VPC 列表 | `vpc` | 显示 6 个 VPC |
| 2 | VPC 健康检查 | `vpc health` | 显示详细健康状态 |
| 3 | 检查子网状态 | 查看响应详情 | 子网可用 |
| 4 | 检查 IGW 状态 | 查看响应详情 | Internet Gateway attached |
| 5 | 检查 NAT Gateway | 查看响应详情 | NAT Gateway 状态 |

**验证点:**
- [ ] VPC 组件状态完整
- [ ] 子网信息准确
- [ ] 网关状态正确

---

### 2.5 TC-005: DynamoDB 表故障

**优先级:** P2  
**风险等级:** 低  
**预计时间:** 10 分钟  

**目标资源:**
- 表: `FrrSensor`, `Music`, `active-number-server`, `ice-json-poc-dynamod`

**测试步骤:**

| 步骤 | 操作 | Chat 命令 | 预期结果 |
|------|------|-----------|----------|
| 1 | 查看 DynamoDB 表 | `dynamodb` | 显示 4 个表 |
| 2 | 健康检查 | `dynamodb health` | 显示表健康状态 |
| 3 | 检查容量模式 | 查看响应详情 | PROVISIONED/PAY_PER_REQUEST |
| 4 | 检查 Throttling | 查看响应详情 | 无 throttling 事件 |

**验证点:**
- [ ] 表状态 ACTIVE
- [ ] 容量模式正确
- [ ] 无性能问题

---

### 2.6 TC-006: 全服务综合健康检查

**优先级:** P0  
**风险等级:** 低  
**预计时间:** 5 分钟  

**测试步骤:**

| 步骤 | 操作 | Chat 命令 | 预期结果 |
|------|------|-----------|----------|
| 1 | 全服务健康检查 | `health` | 显示所有服务状态 |
| 2 | 异常检测 | `anomaly` | 检测异常模式 |
| 3 | 全资源扫描 | `scan` | 扫描所有资源 |
| 4 | 查看帮助 | `help` | 显示可用命令 |

**验证点:**
- [ ] 所有服务响应正常
- [ ] 异常检测功能工作
- [ ] 扫描结果完整

---

### 2.7 TC-007: SOP 系统验证

**优先级:** P1  
**风险等级:** 低  
**预计时间:** 10 分钟  

**测试步骤:**

| 步骤 | 操作 | Chat 命令 | 预期结果 |
|------|------|-----------|----------|
| 1 | 列出所有 SOP | `sop list` | 显示 3 个内置 SOP |
| 2 | 查看 EC2 SOP | `sop show sop-ec2-high-cpu` | 显示详细步骤 |
| 3 | 查看 RDS SOP | `sop show sop-rds-failover` | 显示详细步骤 |
| 4 | 查看 Lambda SOP | `sop show sop-lambda-errors` | 显示详细步骤 |
| 5 | 推荐测试 | `sop suggest high cpu performance` | 推荐相关 SOP |

**验证点:**
- [ ] SOP 列表完整
- [ ] SOP 详情准确
- [ ] 推荐功能工作

---

### 2.8 TC-008: 知识库系统验证

**优先级:** P2  
**风险等级:** 低  
**预计时间:** 10 分钟  

**测试步骤:**

| 步骤 | 操作 | Chat 命令 | 预期结果 |
|------|------|-----------|----------|
| 1 | 查看知识库统计 | `kb stats` | 显示统计信息 |
| 2 | 搜索知识 | `kb search performance` | 搜索结果 |
| 3 | 学习指南 | `learn incident` | 显示学习方法 |
| 4 | 语义搜索 | `kb semantic high cpu` | 语义搜索结果 |

**验证点:**
- [ ] 知识库功能正常
- [ ] 搜索功能工作
- [ ] 语义搜索响应

---

## 3. 测试执行计划

### 3.1 推荐执行顺序

```
Phase 1 (基线建立):
├── TC-006: 全服务综合健康检查
└── TC-007: SOP 系统验证

Phase 2 (核心功能):
├── TC-001: EC2 实例故障模拟
├── TC-002: Lambda 函数错误排查
└── TC-003: 负载均衡器健康检查

Phase 3 (扩展功能):
├── TC-004: VPC 网络故障检测
├── TC-005: DynamoDB 表故障
└── TC-008: 知识库系统验证
```

### 3.2 时间估算

| Phase | 测试用例 | 预计时间 |
|-------|----------|----------|
| Phase 1 | TC-006, TC-007 | 15 分钟 |
| Phase 2 | TC-001, TC-002, TC-003 | 40 分钟 |
| Phase 3 | TC-004, TC-005, TC-008 | 30 分钟 |
| **总计** | | **~85 分钟** |

---

## 4. 风险评估

| 测试用例 | 风险 | 缓解措施 |
|----------|------|----------|
| TC-001 | 停止生产实例 | 选择非关键实例测试 |
| TC-003 | 影响服务可用性 | 在维护窗口执行 |
| TC-002 | 函数执行费用 | 控制调用次数 |

---

## 5. 前置条件

- [x] AgenticAIOps 后端运行正常
- [x] AWS IAM 权限配置完成
- [ ] OpenSearch 权限配置 (向量搜索)
- [x] 测试环境资源确认

---

## 6. 输出文档

- 测试计划: `docs/tests/AWS_FAULT_TEST_PLAN.md` (本文档)
- 测试报告: `docs/tests/AWS_FAULT_TEST_REPORT.md` (执行后生成)
- 问题记录: `docs/tests/ISSUES.md` (如有)

---

**文档状态:** 待审批  
**审批人:** Ma Ronnie  
