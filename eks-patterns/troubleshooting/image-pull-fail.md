# EKS Pattern: ImagePullBackOff

## 概述
**问题类型**: 镜像问题 | **严重级别**: 中
**关键词**: ImagePullBackOff, ErrImagePull, 镜像拉取失败

## 症状
- Pod 状态 `ImagePullBackOff` 或 `ErrImagePull`
- 事件显示 "Failed to pull image"

## 常见原因
1. 镜像名称/tag 错误
2. 私有仓库缺少 imagePullSecrets
3. 网络无法访问仓库
4. Docker Hub 限流

## 诊断步骤
1. `kubectl describe pod <pod>` 查看事件
2. `kubectl get events --field-selector reason=FailedPull`
3. 检查镜像名称和标签

## 解决方案
1. 检查镜像地址拼写
2. 创建 imagePullSecret (ECR)
3. 使用 IRSA 配置 ECR 访问
4. 配置 ECR Pull Through Cache

## 相关 Pattern
- ECR 配置指南
- IRSA 最佳实践
