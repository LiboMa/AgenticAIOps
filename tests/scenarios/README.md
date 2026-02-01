# Test Scenarios for AgenticAIOps MVP

These Kubernetes manifests create intentional issues for testing the agent's diagnostic capabilities.

## Usage

```bash
# Apply a scenario
kubectl apply -f crash-loop-demo.yaml

# Let the agent diagnose
python -m src.cli ask --cluster <cluster> "Why is the crash-demo pod failing?"

# Clean up
kubectl delete -f crash-loop-demo.yaml
```

## Scenarios

| File | Issue Type | Expected Agent Behavior |
|------|-----------|------------------------|
| `crash-loop-demo.yaml` | CrashLoopBackOff | Detect crash, analyze logs, identify exit code |
| `oom-demo.yaml` | OOMKilled | Detect OOM, suggest memory limit increase |
| `image-pull-fail.yaml` | ImagePullBackOff | Detect image issue, suggest fixes |
| `pending-pod.yaml` | Pending | Detect scheduling failure, analyze events |
| `high-restart.yaml` | High restart count | Detect instability, recommend investigation |

## Expected Results

### CrashLoopBackOff
- Agent should find pod in CrashLoopBackOff state
- Should retrieve logs showing the error
- Should recommend checking the command/entrypoint

### OOMKilled
- Agent should detect OOMKilled in container status
- Should show memory limit vs usage
- Should recommend increasing memory limit

### ImagePullBackOff
- Agent should detect ImagePullBackOff
- Should identify the invalid image name
- Should recommend checking image/registry

### Pending
- Agent should detect Pending state
- Should check events for scheduling failure reason
- Should recommend resource or node fixes
