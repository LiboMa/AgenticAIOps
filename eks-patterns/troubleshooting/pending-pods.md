# EKS Pattern: Pod Pending

## 概述
**问题类型**: 调度问题 | **严重级别**: 中-高
**关键词**: Pending, Unschedulable, 无法调度, insufficient

## 症状
- Pod 长时间处于 `Pending` 状态
- 事件显示 `FailedScheduling`
- 描述中出现 `Insufficient` 或 `Unschedulable`

## 常见原因
1. 节点资源不足 (CPU/Memory)
2. nodeSelector 不匹配
3. 节点 taint 无对应 toleration
4. PVC 未绑定
5. ResourceQuota 超限

## 诊断步骤
1. `kubectl describe pod <pod>` 查看调度事件
2. `kubectl describe nodes | grep -A5 "Allocated resources"`
3. `kubectl get pvc` 检查 PVC 状态
4. `kubectl get resourcequota` 检查配额

## 解决方案
1. 扩展节点组 (EKS Auto Scaling)
2. 降低资源 requests
3. 添加 tolerations 匹配节点 taints
4. 修改 nodeSelector/nodeAffinity
5. 检查 PV/StorageClass 配置

## 相关 Pattern
- 资源限制最佳实践
- 节点扩展策略
