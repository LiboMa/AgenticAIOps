# Kubernetes Troubleshooting Decision Tree

## Pod Not Starting

```
Pod status?
├── Pending
│   ├── Events show "FailedScheduling"?
│   │   ├── "Insufficient cpu/memory" → Scale nodes or adjust requests
│   │   ├── "node(s) had taint" → Add toleration or remove taint
│   │   └── "no matching node" → Check nodeSelector/affinity
│   └── Events show "FailedBinding"?
│       └── PVC not bound → Check StorageClass, PV availability
│
├── ContainerCreating (stuck)
│   ├── "Failed to pull image" → Check image name, registry auth, tag
│   ├── "ConfigMap not found" → Create missing ConfigMap
│   └── "Secret not found" → Create missing Secret
│
├── CrashLoopBackOff
│   ├── Exit code 1 → Application error, check logs --previous
│   ├── Exit code 137 → OOMKilled, increase memory limit
│   ├── Exit code 139 → Segfault, check application binary
│   └── Exit code 143 → SIGTERM, check liveness probe timing
│
├── ImagePullBackOff
│   ├── 401 Unauthorized → Check imagePullSecrets
│   ├── 404 Not Found → Verify image:tag exists in registry
│   └── Timeout → Check node network, DNS, registry endpoint
│
└── Error / Unknown
    └── kubectl describe pod → check Events section
```

## Service Not Reachable

```
Service issue?
├── No endpoints?
│   ├── Labels match? → Compare svc.spec.selector vs pod.metadata.labels
│   └── Pods running? → Check pod status first
│
├── Endpoints exist but not reachable?
│   ├── NetworkPolicy blocking? → kubectl get netpol -n <ns>
│   ├── Pod readiness probe failing? → Check probe config + logs
│   └── Wrong port? → Compare svc.spec.ports vs container ports
│
└── External access not working?
    ├── Ingress configured? → Check ingress rules + class
    ├── ALB/NLB healthy? → Check target group health
    └── DNS resolving? → nslookup <service>.<ns>.svc.cluster.local
```

## Node Issues

```
Node NotReady?
├── Conditions show MemoryPressure?
│   └── Check pods with high memory → evict or add capacity
├── Conditions show DiskPressure?
│   └── Clean up: container images, logs, /tmp
├── Conditions show PIDPressure?
│   └── Find process leak: ps aux | wc -l
├── Kubelet not running?
│   └── systemctl status kubelet → journalctl -u kubelet
└── Network unreachable?
    └── Check VPC, SG, NACLs, ENI attachment
```
