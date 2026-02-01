# AgenticAIOps Plugin API Reference

## Overview

The Plugin API allows dynamic management of service plugins and clusters.

## Base URL

```
http://localhost:8000/api
```

## Authentication

Currently no authentication required (internal use).

---

## Plugin Endpoints

### List Plugins

```http
GET /api/plugins
```

**Response:**
```json
{
  "plugins": [
    {
      "plugin_id": "eks-default",
      "plugin_type": "eks",
      "name": "EKS Default",
      "description": "Manage and monitor Amazon EKS Kubernetes clusters",
      "icon": "☸️",
      "status": "enabled",
      "enabled": true,
      "config": {"regions": ["ap-southeast-1"]},
      "tools_count": 6
    }
  ],
  "available_types": [
    {"type": "eks", "name": "Amazon EKS", "description": "...", "icon": "☸️"},
    {"type": "ec2", "name": "Amazon EC2", "description": "...", "icon": "🖥️"},
    {"type": "lambda", "name": "AWS Lambda", "description": "...", "icon": "λ"},
    {"type": "hpc", "name": "AWS ParallelCluster", "description": "...", "icon": "🖧"}
  ]
}
```

### Create Plugin

```http
POST /api/plugins
Content-Type: application/json

{
  "plugin_type": "ec2",
  "name": "My EC2 Monitor",
  "config": {
    "regions": ["ap-southeast-1", "us-east-1"]
  }
}
```

**Response:**
```json
{
  "status": "created",
  "plugin": {
    "plugin_id": "abc12345",
    "plugin_type": "ec2",
    "name": "My EC2 Monitor",
    "status": "enabled",
    ...
  }
}
```

### Delete Plugin

```http
DELETE /api/plugins/{plugin_id}
```

**Response:**
```json
{
  "status": "removed",
  "plugin_id": "abc12345"
}
```

### Enable Plugin

```http
POST /api/plugins/{plugin_id}/enable
```

**Response:**
```json
{
  "status": "enabled",
  "plugin": {...}
}
```

### Disable Plugin

```http
POST /api/plugins/{plugin_id}/disable
```

**Response:**
```json
{
  "status": "disabled",
  "plugin": {...}
}
```

### Get Plugin Status

```http
GET /api/plugins/{plugin_id}/status
```

**Response (EKS):**
```json
{
  "plugin_type": "eks",
  "icon": "☸️",
  "name": "Amazon EKS",
  "total_clusters": 1,
  "healthy_clusters": 1,
  "clusters": [
    {"id": "eks-ap-southeast-1-testing-cluster", "name": "testing-cluster", "region": "ap-southeast-1"}
  ]
}
```

**Response (EC2):**
```json
{
  "plugin_type": "ec2",
  "icon": "🖥️",
  "name": "Amazon EC2",
  "total_instances": 15,
  "running": 4,
  "stopped": 11,
  "instances": [...]
}
```

---

## Cluster Endpoints

### List Clusters

```http
GET /api/clusters
GET /api/clusters?plugin_type=eks
```

**Response:**
```json
{
  "clusters": [
    {
      "cluster_id": "eks-ap-southeast-1-testing-cluster",
      "name": "testing-cluster",
      "region": "ap-southeast-1",
      "plugin_type": "eks",
      "config": {"cluster_name": "testing-cluster"}
    }
  ],
  "active_cluster": {
    "cluster_id": "eks-ap-southeast-1-testing-cluster",
    ...
  }
}
```

### Add Cluster

```http
POST /api/clusters
Content-Type: application/json

{
  "cluster_id": "eks-us-east-1-prod",
  "name": "prod-cluster",
  "region": "us-east-1",
  "plugin_type": "eks",
  "config": {}
}
```

**Response:**
```json
{
  "status": "added",
  "cluster": {...}
}
```

### Activate Cluster

```http
POST /api/clusters/{cluster_id}/activate
```

**Response:**
```json
{
  "status": "activated",
  "cluster": {...}
}
```

### Get Active Cluster

```http
GET /api/clusters/active
```

**Response:**
```json
{
  "cluster_id": "eks-ap-southeast-1-testing-cluster",
  "name": "testing-cluster",
  "region": "ap-southeast-1",
  "plugin_type": "eks",
  "config": {...}
}
```

---

## Registry Status

### Get Registry Status

```http
GET /api/registry/status
```

**Response:**
```json
{
  "available_plugin_types": 4,
  "registered_plugins": 3,
  "enabled_plugins": 3,
  "clusters": 1,
  "active_cluster": "eks-ap-southeast-1-testing-cluster",
  "plugins": [...],
  "cluster_list": [...]
}
```

---

## Plugin Types

| Type | Icon | Description |
|------|------|-------------|
| `eks` | ☸️ | Amazon EKS Kubernetes clusters |
| `ec2` | 🖥️ | Amazon EC2 instances |
| `lambda` | λ | AWS Lambda functions |
| `hpc` | 🖧 | AWS ParallelCluster HPC |

---

## Error Responses

### 404 Not Found

```json
{
  "detail": "Plugin not found"
}
```

### 400 Bad Request

```json
{
  "detail": "Unknown plugin type: xyz"
}
```

---

## Examples

### Create and Test EC2 Plugin

```bash
# Create EC2 plugin
curl -X POST http://localhost:8000/api/plugins \
  -H "Content-Type: application/json" \
  -d '{"plugin_type": "ec2", "name": "EC2 Monitor", "config": {"regions": ["ap-southeast-1"]}}'

# Check status
curl http://localhost:8000/api/plugins/$(PLUGIN_ID)/status
```

### Switch Active Cluster

```bash
# List clusters
curl http://localhost:8000/api/clusters

# Activate different cluster
curl -X POST http://localhost:8000/api/clusters/eks-us-east-1-prod/activate

# Verify
curl http://localhost:8000/api/clusters/active
```
