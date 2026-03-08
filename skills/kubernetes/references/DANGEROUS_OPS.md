# Kubernetes Dangerous Operations Protocol

## Operations Requiring Approval

| Operation | Risk | Approval Level | Max Concurrent |
|-----------|------|----------------|----------------|
| `delete pod` | Low (K8s recreates) | L0 — auto | unlimited |
| `delete deploy/svc` | Medium | L1 — single | 1 |
| `drain node` | High | L2 — human | 1 |
| `cordon node` | Medium | L1 — single | 1 |
| `taint NoExecute` | High | L2 — human | 1 |
| `apply -f` (mutation) | Varies | L1 — single | 1 |
| `scale --replicas=0` | High | L2 — human | 1 |

## Pre-flight Checklist (All Dangerous Ops)

1. ☐ Confirm target namespace is NOT kube-system / kube-public / kube-node-lease
2. ☐ Confirm target resource identity (name, namespace, cluster)
3. ☐ Check PodDisruptionBudgets (`kubectl get pdb -n <ns>`)
4. ☐ Verify rollback plan exists
5. ☐ Obtain approval_token

## Drain Protocol

```
# 1. Pre-flight
kubectl get pdb -A
kubectl describe node <name>  # check existing taints
kubectl get pods --field-selector spec.nodeName=<name> -A

# 2. Cordon first (stop new scheduling)
kubectl cordon <name>

# 3. Drain (with safety flags)
kubectl drain <name> \
  --ignore-daemonsets \
  --pod-selector='app!=critical-singleton' \
  --timeout=300s \
  --grace-period=30

# 4. Verify pods rescheduled
kubectl get pods -A --field-selector status.phase!=Running

# 5. After maintenance: uncordon
kubectl uncordon <name>
```

## Rollback Procedures

### Deployment Rollback
```bash
kubectl rollout undo deploy/<name> -n <ns>
kubectl rollout status deploy/<name> -n <ns>  # verify
```

### Scale Recovery
```bash
kubectl scale deploy/<name> --replicas=<original> -n <ns>
```

### Node Recovery
```bash
kubectl uncordon <name>
kubectl taint nodes <name> <key>-  # remove taint
```
