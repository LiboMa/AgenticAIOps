# Sample Workloads

This directory contains sample Kubernetes workloads for testing AgenticAIOps.

## Available Workloads

### 1. Online Shop (`onlineshop.yaml`)
E-commerce application with microservices architecture:
- `shop-frontend` - Nginx web server (2 replicas)
- `shop-api` - Backend API service (2 replicas)
- `shop-cache` - Redis cache (1 replica)
- `shop-worker` - Background job processor (1 replica)

### 2. Bookstore (`bookstore.yaml`)
Book catalog application:
- `bookstore-web` - Web frontend (2 replicas)
- `bookstore-api` - REST API (2 replicas)
- `bookstore-db` - PostgreSQL database (1 replica)

### 3. Faulty Workloads (`faulty-workloads.yaml`)
Intentionally broken applications for testing diagnostics:

| Name | Scenario | Expected Issue |
|------|----------|----------------|
| `crashloop-app` | CrashLoopBackOff | Container exits with error |
| `oom-app` | OOMKilled | Memory limit exceeded |
| `imagepull-fail` | ImagePullBackOff | Non-existent image |
| `pending-pod` | Pending | Unschedulable (huge resources) |
| `high-restart-app` | High Restarts | Exits every 60 seconds |

## Deployment

```bash
# Deploy normal workloads
kubectl apply -f onlineshop.yaml
kubectl apply -f bookstore.yaml

# Deploy faulty workloads (for testing)
kubectl apply -f faulty-workloads.yaml

# Check status
kubectl get pods -n onlineshop
kubectl get pods -n bookstore
kubectl get pods -n faulty-apps
```

## Cleanup

```bash
kubectl delete namespace onlineshop bookstore faulty-apps
```

## Testing with AgenticAIOps

After deploying, test the agent with queries like:
- "Check the health of pods in the onlineshop namespace"
- "Why is crashloop-app failing?"
- "What's wrong with the pending-pod?"
- "Show me pods with high restart counts"
