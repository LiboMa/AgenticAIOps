# EKS Pattern: OOM Killed

## 概述
**问题类型**: 资源问题 | **严重级别**: 高
**关键词**: OOM, OOMKilled, Out of Memory, 内存不足, killed

## 症状
- Pod 状态显示 `OOMKilled`
- Pod 反复重启
- `kubectl describe pod` 显示 `Reason: OOMKilled`

## 常见原因
1. 内存限制设置过低
2. 内存泄漏
3. 突发流量
4. JVM 堆设置不当

## 诊断步骤
1. `kubectl describe pod <pod> | grep -A5 "Last State"`
2. `kubectl get pod <pod> -o jsonpath='{.spec.containers[*].resources}'`
3. `kubectl top pod <pod>`

## 解决方案
1. 增加 memory limits
2. 优化应用内存 (Java: -Xmx 设为 limits 的 70-80%)
3. 配置 HPA 应对突发流量

## 相关 Pattern
- 资源限制最佳实践
- HPA 配置指南
