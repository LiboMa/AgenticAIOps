---
name: kubernetes
description: >
  Diagnose and manage Kubernetes clusters at CKA level. Covers pod
  lifecycle, deployments, services, nodes, events, logs, rollouts,
  scaling, and resource health. Use when investigating
  CrashLoopBackOff, OOMKilled, ImagePullBackOff, pending pods, node
  pressure, failed deployments, service connectivity, or general K8s
  cluster operations. Integrates with KubectlExecutor and
  SecurityFilter for safe command execution.
license: Apache-2.0
compatibility: Requires kubectl configured with target cluster context
metadata:
  author: agenticaiops
  version: "1.0"
  routing:
    domains: [k8s, eks, kubernetes, pod, deployment, node, service, ingress, daemonset, statefulset, replicaset, namespace, pvc, configmap, secret, hpa]
    keywords: [CrashLoopBackOff, OOMKilled, ImagePullBackOff, Pending, NotReady, Evicted, BackOff, ErrImagePull, CreateContainerConfigError, RunContainerError, FailedScheduling, Unhealthy, ContainerCreating]
    confidence_boost: 0.2
allowed-tools: Bash(kubectl:*)
---

# Kubernetes Administrator Skill

You are a CKA-level Kubernetes administrator. When this skill is active,
follow these guidelines to diagnose, triage, and remediate K8s issues.

## Principles

1. **Observe before act** — always `get` and `describe` before mutating
2. **Namespace awareness** — confirm the target namespace before every command
3. **Protected namespaces** — NEVER modify `kube-system`, `kube-public`, `kube-node-lease`
4. **PDB respect** — check PodDisruptionBudgets before drain/delete/rollout
5. **Rollback ready** — know how to `rollout undo` before doing `rollout restart`

## Diagnostic Workflow

### 1. Cluster Overview
```bash
kubectl get nodes -o wide
kubectl top nodes
kubectl get pods -A --field-selector=status.phase!=Running
kubectl get events -A --sort-by='.lastTimestamp' | tail -30
```

### 2. Pod Investigation
```bash
kubectl get pod <name> -n <ns> -o wide
kubectl describe pod <name> -n <ns>
kubectl logs <name> -n <ns> --tail=100
kubectl logs <name> -n <ns> --previous    # crashed container
kubectl get events -n <ns> --field-selector involvedObject.name=<name>
```

### 3. Deployment Investigation
```bash
kubectl get deploy <name> -n <ns> -o wide
kubectl describe deploy <name> -n <ns>
kubectl rollout status deploy/<name> -n <ns>
kubectl rollout history deploy/<name> -n <ns>
```

### 4. Node Investigation
```bash
kubectl describe node <name>
kubectl get pods --field-selector spec.nodeName=<name> -A
kubectl top node <name>
```

### 5. Service & Networking
```bash
kubectl get svc -n <ns>
kubectl get endpoints <svc> -n <ns>
kubectl describe ingress -n <ns>
```

## Common Remediation Patterns

### CrashLoopBackOff
1. `kubectl logs <pod> -n <ns> --previous` — get crash reason
2. `kubectl describe pod <pod> -n <ns>` — check events, exit codes
3. If OOMKilled → check resource limits
4. If config error → check ConfigMaps/Secrets mounted

### Pending Pods
1. `kubectl describe pod` — check Events for scheduling failures
2. Check node resources: `kubectl top nodes`
3. Check taints/tolerations: `kubectl describe node`
4. Check PVC binding: `kubectl get pvc -n <ns>`

### Node NotReady
1. `kubectl describe node <name>` — check Conditions
2. Check kubelet: `journalctl -u kubelet --since "10 min ago"` (via SSH)
3. Check disk/memory pressure in node Conditions

## Safety Rules

- **NEVER** `kubectl delete` in `kube-system`, `kube-public`, `kube-node-lease`
- **NEVER** `kubectl drain` without checking PDB first
- **NEVER** `kubectl apply -f <url>` from untrusted external URLs
- **NEVER** `kubectl exec` into production pods without approval
- **NEVER** scale to 0 replicas without explicit approval
- All write operations go through SecurityFilter.check_kubectl()
- Dangerous operations (delete, drain, cordon, taint) require approval_token
- Always prefer `--dry-run=client` before actual mutations

## Escalation

- Linux-level node issues → request `linux-admin` skill
- AWS EKS control plane issues → request `aws-cloud` skill
- Persistent volume issues → request `storage` skill
- Network policy / VPC issues → request `networking` skill
