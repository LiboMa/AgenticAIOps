# AgenticAIOps 生产环境 & 多账户分析

**日期:** 2026-02-12
**参与者:** Ma Ronnie, Researcher, Developer, Architect, Tester

---

## 1. 核心优点 (团队共识)

| 优点 | 描述 | 影响 |
|------|------|------|
| 自然语言交互 | 降低运维门槛，新人无需记忆 CLI | 效率 +50% |
| 闭环知识沉淀 | Pattern → Vector DB → RCA | 经验不丢失 |
| SOP 标准化 | 可追溯、减少人为错误 | 质量提升 |
| AWS 原生集成 | Boto3 + IAM Role，无外部依赖 | 安全性 |
| 快速响应 | Chat 比 Console 快 5-10x | MTTR 降低 |
| 模块化设计 | Scanner/Ops 分离，已支持 13 服务 | 可扩展 |

---

## 2. 核心缺点 & 风险

### 2.1 安全风险

| 风险 | 当前状态 | 生产要求 | 优先级 |
|------|---------|---------|--------|
| 敏感操作无审批 | ❌ 直接执行 | ✅ 必须审批 | P0 |
| 无 RBAC | ❌ 单一角色 | ✅ 分层权限 | P1 |
| 无 MFA | ❌ | ✅ 危险操作需 MFA | P1 |
| 无 Dry-run | ❌ | ✅ 预览影响 | P0 |

### 2.2 架构限制

| 限制 | 描述 | 影响 |
|------|------|------|
| 单账户设计 | 无 Cross-Account 支持 | 企业无法使用 |
| 单点部署 | 无 HA/灾备 | 可用性风险 |
| 同步 API | 大规模扫描阻塞 | 性能瓶颈 |
| LLM 依赖 | Bedrock 中断 = 系统瘫痪 | 可靠性风险 |

### 2.3 合规缺失

| 要求 | 当前状态 | SOC2/ISO27001 |
|------|---------|---------------|
| 操作审计日志 | ⚠️ 仅 CloudTrail | ✅ 应用层审计 |
| 数据分类 | ❌ | ✅ 敏感数据标记 |
| 访问控制 | ⚠️ 粗粒度 | ✅ 细粒度 RBAC |
| 变更管理 | ❌ | ✅ 审批流程 |

---

## 3. 多账户架构挑战

### 3.1 典型企业账户结构

```
AWS Organizations
├── Management Account (Org Master)
├── Security Account (CloudTrail, GuardDuty, Security Hub)
├── Shared Services Account (DNS, AD, Transit Gateway)
├── Log Archive Account (集中日志)
├── Workload Accounts
│   ├── Dev (开发)
│   ├── Staging (测试)
│   ├── Prod (生产)
│   └── ... (可能 50-500+ 账户)
```

### 3.2 实现方案对比

| 方案 | 优点 | 缺点 |
|------|------|------|
| A: 中心化 | 统一知识库 | 单点故障，跨账户延迟 |
| B: 分布式 | 高可用，低延迟 | 知识孤岛 |
| C: 混合 | 平衡性能与一致性 | 架构复杂 |

### 3.3 推荐: Cross-Account AssumeRole

```python
class AWSClientFactory:
    def __init__(self, account_registry):
        self.accounts = account_registry
    
    def get_client(self, service, account_id=None):
        if account_id:
            sts = boto3.client('sts')
            creds = sts.assume_role(
                RoleArn=f'arn:aws:iam::{account_id}:role/AIOps-CrossAccountRole',
                RoleSessionName='AgenticAIOps'
            )['Credentials']
            return boto3.client(
                service,
                aws_access_key_id=creds['AccessKeyId'],
                aws_secret_access_key=creds['SecretAccessKey'],
                aws_session_token=creds['SessionToken']
            )
        return boto3.client(service)
```

---

## 4. 成本估算

### 4.1 单账户月度成本

| 组件 | 规格 | 成本 (USD) |
|------|------|------------|
| EC2 | m6i.xlarge | ~$140 |
| OpenSearch | 3x r7g.large | ~$300 |
| Bedrock | Claude Sonnet | ~$50-200 |
| S3 + 传输 | - | ~$20 |
| **Total** | | **~$510-670** |

### 4.2 多账户扩展成本

| 账户数 | 独立部署 | 共享架构 |
|--------|---------|---------|
| 10 | $5,100-6,700 | $1,500-2,000 |
| 50 | $25,500-33,500 | $3,000-5,000 |
| 100 | $51,000-67,000 | $5,000-8,000 |

---

## 5. 改进路线图

### Phase 1: 安全加固 (1-2 周)

- [ ] 危险操作二次确认
- [ ] Dry-run 模式
- [ ] 操作审计日志 (S3 + CloudWatch Logs)
- [ ] 敏感操作白名单

### Phase 2: 多账户支持 (2-4 周)

- [ ] Account Registry 配置
- [ ] Cross-Account AssumeRole
- [ ] `use account <name>` 命令
- [ ] 账户级权限配置

### Phase 3: 高可用 (4-6 周)

- [ ] 多 AZ 部署 + ALB
- [ ] OpenSearch 跨区域复制
- [ ] LLM 降级策略 (fallback to rules)
- [ ] 自动故障转移

### Phase 4: 企业级功能 (6-8 周)

- [ ] RBAC 权限分层
- [ ] ITSM 集成 (ServiceNow, Jira)
- [ ] 变更窗口控制
- [ ] SLA Dashboard

---

## 6. 关键决策点

### Q1: Agent 自主性级别?

| 选项 | 描述 | 适用场景 |
|------|------|---------|
| A: 完全自主 | Agent 直接执行所有操作 | 开发/测试环境 |
| B: 审批模式 | 所有操作需人工批准 | 高安全要求 |
| C: 分级策略 | Dev 自主 / Prod 审批 | **推荐** |

### Q2: 多账户规模?

| 规模 | 架构建议 |
|------|---------|
| <10 | 单中心，Profile 切换 |
| 10-50 | 混合架构，Hub-Spoke |
| 50+ | 分布式 + 中心化知识库 |

### Q3: 最关心的风险?

- 安全: 误操作导致生产事故
- 合规: 审计要求不满足
- 可用性: 系统单点故障
- 成本: 运营成本不可控

---

## 7. 总结

**适用场景:**
- ✅ 小型团队 (1-10 账户)
- ✅ 开发/测试环境
- ⚠️ 生产环境 (需加固后)
- ❌ 大型企业 (50+ 账户，需重构)

**核心价值:**
- 运维效率提升 30-50%
- 知识积累不丢失
- 标准化减少人为错误

**必须改进:**
- P0: 操作审批 + Dry-run
- P1: 多账户支持
- P2: 高可用部署

---

*文档结束*
