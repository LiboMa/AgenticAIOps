# EKS Pattern: CrashLoopBackOff

## 概述
**问题类型**: 应用问题 | **严重级别**: 高
**关键词**: CrashLoopBackOff, crash loop, 崩溃循环, backoff

## 症状
- Pod 状态 `CrashLoopBackOff`
- 重启次数不断增加
- BackOff 时间递增 (10s, 20s, 40s...)

## 常见原因
1. 应用启动失败 (配置错误/依赖不可用)
2. liveness probe 配置不当
3. 资源不足 (OOM/CPU)
4. 镜像 entrypoint 错误

## 诊断步骤
1. `kubectl describe pod <pod>` 查看事件
2. `kubectl logs <pod> --previous` 查看崩溃日志
3. 检查退出码: 137=OOM, 1=应用错误

## 解决方案
1. 修复应用配置/环境变量
2. 调整探针: 增加 initialDelaySeconds
3. 检查依赖服务连通性
4. 使用 `kubectl debug` 调试

## 相关 Pattern
- OOM Killed 处理
- 探针配置最佳实践
