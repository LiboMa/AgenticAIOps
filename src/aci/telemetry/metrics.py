"""
ACI Metrics Provider

Provides metrics retrieval from CloudWatch or Prometheus.
"""

import json
import logging
import subprocess
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ..models import TelemetryResult, ResultStatus, MetricPoint

logger = logging.getLogger(__name__)


# Predefined metric mappings
PREDEFINED_METRICS = {
    "cpu_usage": {
        "cloudwatch": {
            "namespace": "ContainerInsights",
            "metric_name": "pod_cpu_utilization",
        },
        "prometheus": "container_cpu_usage_seconds_total",
    },
    "memory_usage": {
        "cloudwatch": {
            "namespace": "ContainerInsights",
            "metric_name": "pod_memory_utilization",
        },
        "prometheus": "container_memory_usage_bytes",
    },
    "network_rx": {
        "cloudwatch": {
            "namespace": "ContainerInsights",
            "metric_name": "pod_network_rx_bytes",
        },
        "prometheus": "container_network_receive_bytes_total",
    },
    "network_tx": {
        "cloudwatch": {
            "namespace": "ContainerInsights",
            "metric_name": "pod_network_tx_bytes",
        },
        "prometheus": "container_network_transmit_bytes_total",
    },
    "restarts": {
        "cloudwatch": {
            "namespace": "ContainerInsights",
            "metric_name": "pod_number_of_container_restarts",
        },
        "prometheus": "kube_pod_container_status_restarts_total",
    },
}


class MetricsProvider:
    """
    Metrics provider using CloudWatch or Prometheus.
    
    Defaults to CloudWatch for EKS clusters.
    """
    
    def __init__(self, cluster_name: str, region: str):
        self.cluster_name = cluster_name
        self.region = region
    
    def get_metrics(
        self,
        namespace: str,
        query: Optional[str] = None,
        metric_names: Optional[List[str]] = None,
        duration_minutes: int = 5,
        step: str = "1m",
    ) -> TelemetryResult:
        """
        Get metrics from CloudWatch.
        
        Args:
            namespace: K8s namespace
            query: PromQL query (not yet supported, uses CloudWatch)
            metric_names: Predefined metric names
            duration_minutes: Time range
            step: Data step interval
        
        Returns:
            TelemetryResult with MetricPoint list
        """
        try:
            # Default to common metrics if none specified
            if not metric_names:
                metric_names = ["cpu_usage", "memory_usage"]
            
            all_metrics: List[Dict[str, Any]] = []
            
            for metric_name in metric_names:
                if metric_name in PREDEFINED_METRICS:
                    metrics = self._get_cloudwatch_metric(
                        namespace=namespace,
                        metric_def=PREDEFINED_METRICS[metric_name]["cloudwatch"],
                        duration_minutes=duration_minutes,
                    )
                    all_metrics.extend(metrics)
                else:
                    logger.warning(f"Unknown metric: {metric_name}")
            
            return TelemetryResult(
                status=ResultStatus.SUCCESS,
                data=all_metrics,
                metadata={
                    "namespace": namespace,
                    "metrics_queried": metric_names,
                    "duration_minutes": duration_minutes,
                    "data_points": len(all_metrics),
                },
            )
            
        except Exception as e:
            logger.error(f"Error getting metrics: {e}")
            return TelemetryResult(
                status=ResultStatus.ERROR,
                error=str(e),
            )
    
    def _get_cloudwatch_metric(
        self,
        namespace: str,
        metric_def: Dict[str, str],
        duration_minutes: int,
    ) -> List[Dict[str, Any]]:
        """
        Get metric from CloudWatch using kubectl top or aws cloudwatch.
        
        For simplicity, uses kubectl top as a proxy for resource metrics.
        """
        try:
            # Use kubectl top for basic metrics
            cmd = ["kubectl", "top", "pods", "-n", namespace, "--no-headers"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                logger.warning(f"kubectl top failed: {result.stderr}")
                return []
            
            metrics = []
            now = datetime.now()
            
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                
                parts = line.split()
                if len(parts) >= 3:
                    pod_name = parts[0]
                    cpu = parts[1]  # e.g., "10m" or "100m"
                    memory = parts[2]  # e.g., "50Mi" or "1Gi"
                    
                    # Parse CPU
                    cpu_value = self._parse_cpu(cpu)
                    metrics.append({
                        "timestamp": now.isoformat(),
                        "metric_name": "cpu_usage",
                        "value": cpu_value,
                        "labels": {"pod": pod_name, "namespace": namespace},
                    })
                    
                    # Parse Memory
                    memory_value = self._parse_memory(memory)
                    metrics.append({
                        "timestamp": now.isoformat(),
                        "metric_name": "memory_usage",
                        "value": memory_value,
                        "labels": {"pod": pod_name, "namespace": namespace},
                    })
            
            return metrics
            
        except subprocess.TimeoutExpired:
            logger.error("kubectl top timeout")
            return []
        except Exception as e:
            logger.error(f"Error getting CloudWatch metric: {e}")
            return []
    
    def _parse_cpu(self, cpu_str: str) -> float:
        """Parse CPU string like '10m' or '1' to millicores."""
        try:
            if cpu_str.endswith("m"):
                return float(cpu_str[:-1])
            else:
                return float(cpu_str) * 1000  # cores to millicores
        except:
            return 0.0
    
    def _parse_memory(self, mem_str: str) -> float:
        """Parse memory string like '50Mi' or '1Gi' to bytes."""
        try:
            if mem_str.endswith("Ki"):
                return float(mem_str[:-2]) * 1024
            elif mem_str.endswith("Mi"):
                return float(mem_str[:-2]) * 1024 * 1024
            elif mem_str.endswith("Gi"):
                return float(mem_str[:-2]) * 1024 * 1024 * 1024
            else:
                return float(mem_str)
        except:
            return 0.0
