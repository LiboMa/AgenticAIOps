# AgenticAIOps 测试指南

## 环境准备

### 1. 前置条件
```bash
# 确认在正确目录
cd /home/ubuntu/agentic-aiops-mvp

# 确认 EKS 集群可访问
kubectl get nodes

# 确认 Python 环境
source venv/bin/activate
```

### 2. 启动服务

**后端 API (FastAPI)**
```bash
cd /home/ubuntu/agentic-aiops-mvp
source venv/bin/activate
python api_server.py
# 服务运行在 http://localhost:8000
```

**前端 Dashboard (React)**
```bash
cd /home/ubuntu/agentic-aiops-mvp/dashboard
npm run dev -- --host 0.0.0.0
# 服务运行在 http://localhost:5173
```

---

## 测试步骤

### 1. API 健康检查
```bash
# 健康检查
curl http://localhost:8000/health

# 集群信息
curl http://localhost:8000/api/cluster/info

# 预期输出:
# {"name":"...:cluster/testing-cluster","status":"ACTIVE",...}
```

### 2. EKS Status 测试
```bash
# 获取所有 Pods
curl http://localhost:8000/api/pods | python3 -m json.tool | head -30

# 获取所有 Nodes
curl http://localhost:8000/api/nodes | python3 -m json.tool

# 获取 Deployments
curl http://localhost:8000/api/deployments | python3 -m json.tool
```

**预期结果:**
- Pods: ~29 个
- Nodes: 2 个
- 包含 onlineshop, bookstore, faulty-apps 等命名空间

### 3. 异常检测测试
```bash
# 获取检测到的异常
curl http://localhost:8000/api/anomalies | python3 -m json.tool
```

**预期结果:**
- 检测到 `crashloop-app` (CrashLoopBackOff)
- 检测到 `high-restart-app` (高重启次数)

### 4. Chat API 测试
```bash
# 测试 Intent Classification
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What pods are having issues?"}' | python3 -m json.tool

# 测试中文
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "集群状态怎么样?"}' | python3 -m json.tool
```

**预期结果:**
- `intent`: "diagnose" (问题类查询)
- `intent`: "monitor" (状态类查询)
- `confidence`: 0.33 - 1.0

### 5. Dashboard UI 测试

打开浏览器访问: `http://<服务器IP>:5173`

#### 5.1 Chat 页面
- [ ] 输入 "Check cluster health" → 收到响应
- [ ] 输入中文 "有哪些 Pod 出问题了?" → 收到响应
- [ ] 消息显示正确 (用户/助手区分)

#### 5.2 EKS Status 页面
- [ ] 显示集群名称和版本
- [ ] 显示节点列表 (2 个 Ready)
- [ ] 显示 Pod 列表 (~29 个)
- [ ] 状态颜色正确 (绿色=Running, 红色=Error)

#### 5.3 Anomalies 页面
- [ ] 显示 Critical/Warning 数量统计
- [ ] 列出检测到的异常
- [ ] 点击展开显示 AI 建议
- [ ] CrashLoopBackOff 标记为 Critical

#### 5.4 RCA Reports 页面
- [ ] 显示历史报告卡片
- [ ] 点击 "View Report" 打开详情
- [ ] 显示根因、症状、解决方案

---

## 单元测试

### Intent Classification
```bash
cd /home/ubuntu/agentic-aiops-mvp
source venv/bin/activate
python src/intent_classifier.py
```

### Multi-Agent Voting
```bash
python src/multi_agent_voting.py
```

### kubectl Wrapper
```bash
python src/kubectl_wrapper.py
```

---

## 测试场景

### 场景 1: 诊断 CrashLoopBackOff
1. 在 Chat 中输入: "Why is crashloop-app crashing?"
2. 预期: Intent=diagnose, 推荐工具=get_pods, get_events, get_pod_logs

### 场景 2: 查看集群状态
1. 在 Chat 中输入: "How is my cluster doing?"
2. 预期: Intent=monitor, 推荐工具=get_cluster_health, get_pods, get_nodes

### 场景 3: 扩容请求
1. 在 Chat 中输入: "Scale shop-frontend to 5 replicas"
2. 预期: Intent=scale, 推荐工具=scale_deployment, get_hpa

---

## 常见问题

### API 无响应
```bash
# 检查进程
ps aux | grep api_server
# 检查端口
netstat -tlnp | grep 8000
# 查看日志
cat /tmp/api.log
```

### kubectl 超时
```bash
# 测试 kubectl 连接
kubectl get nodes --request-timeout=5s
# 检查 kubeconfig
kubectl config current-context
```

### 前端无法连接后端
```bash
# 确认后端运行
curl http://localhost:8000/health
# 检查 CORS
# 确认 api_server.py 中 CORS 配置正确
```
