"""
ACI Prometheus Metrics Provider

Provides metrics retrieval from Prometheus server.
"""

import json
import logging
import re
import requests
from datetime import datetime, timedelta, timezone
from string import Template
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from ..models import TelemetryResult, ResultStatus, MetricPoint
from ...utils.time import ensure_aware

logger = logging.getLogger(__name__)


# Common Kubernetes metrics - using $namespace for Template substitution
# to avoid conflict with PromQL {} syntax
K8S_METRICS = {
    "cpu_usage": 'sum(rate(container_cpu_usage_seconds_total{namespace="$namespace"}[5m])) by (pod)',
    "memory_usage": 'sum(container_memory_usage_bytes{namespace="$namespace"}) by (pod)',
    "network_rx": 'sum(rate(container_network_receive_bytes_total{namespace="$namespace"}[5m])) by (pod)',
    "network_tx": 'sum(rate(container_network_transmit_bytes_total{namespace="$namespace"}[5m])) by (pod)',
    "restarts": 'sum(kube_pod_container_status_restarts_total{namespace="$namespace"}) by (pod)',
    "pod_ready": 'kube_pod_status_ready{namespace="$namespace",condition="true"}',
    "pod_phase": 'kube_pod_status_phase{namespace="$namespace"}',
    "container_oom": 'kube_pod_container_status_last_terminated_reason{namespace="$namespace",reason="OOMKilled"}',
}


class PrometheusProvider:
    """
    Prometheus metrics provider.
    
    Queries Prometheus server for Kubernetes metrics.
    """
    
    def __init__(
        self,
        prometheus_url: str = "http://prometheus-server.monitoring:80",
        timeout: int = 30,
    ):
        """
        Initialize Prometheus provider.
        
        Args:
            prometheus_url: Prometheus server URL
            timeout: Query timeout in seconds
        """
        self.prometheus_url = prometheus_url.rstrip("/")
        self.timeout = timeout
    
    def query(
        self,
        query: str,
        time: Optional[datetime] = None,
    ) -> TelemetryResult:
        """
        Execute instant query.
        
        Args:
            query: PromQL query
            time: Query time (default: now)
        
        Returns:
            TelemetryResult with metric data
        """
        try:
            url = urljoin(self.prometheus_url, "/api/v1/query")
            params = {"query": query}
            
            if time:
                params["time"] = time.timestamp()
            
            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get("status") != "success":
                return TelemetryResult(
                    status=ResultStatus.ERROR,
                    error=data.get("error", "Unknown Prometheus error"),
                )
            
            # Parse result
            result_data = data.get("data", {}).get("result", [])
            metrics = self._parse_instant_result(result_data)
            
            return TelemetryResult(
                status=ResultStatus.SUCCESS,
                data=[m.to_dict() for m in metrics],
                metadata={
                    "query": query,
                    "result_type": data.get("data", {}).get("resultType"),
                    "count": len(metrics),
                },
            )
            
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Prometheus connection failed: {e}")
            return TelemetryResult(
                status=ResultStatus.ERROR,
                error=f"Cannot connect to Prometheus at {self.prometheus_url}",
            )
        except requests.exceptions.Timeout:
            return TelemetryResult(
                status=ResultStatus.TIMEOUT,
                error=f"Prometheus query timeout after {self.timeout}s",
            )
        except Exception as e:
            logger.error(f"Prometheus query error: {e}")
            return TelemetryResult(
                status=ResultStatus.ERROR,
                error=str(e),
            )
    
    def query_range(
        self,
        query: str,
        start: datetime,
        end: datetime,
        step: str = "1m",
    ) -> TelemetryResult:
        """
        Execute range query.
        
        Args:
            query: PromQL query
            start: Start time
            end: End time
            step: Query step (e.g., "1m", "5m")
        
        Returns:
            TelemetryResult with metric data
        """
        try:
            url = urljoin(self.prometheus_url, "/api/v1/query_range")
            params = {
                "query": query,
                "start": start.timestamp(),
                "end": end.timestamp(),
                "step": step,
            }
            
            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get("status") != "success":
                return TelemetryResult(
                    status=ResultStatus.ERROR,
                    error=data.get("error", "Unknown Prometheus error"),
                )
            
            # Parse result
            result_data = data.get("data", {}).get("result", [])
            metrics = self._parse_range_result(result_data)
            
            return TelemetryResult(
                status=ResultStatus.SUCCESS,
                data=metrics,
                metadata={
                    "query": query,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "step": step,
                    "series_count": len(result_data),
                },
            )
            
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Prometheus connection failed: {e}")
            return TelemetryResult(
                status=ResultStatus.ERROR,
                error=f"Cannot connect to Prometheus at {self.prometheus_url}",
            )
        except requests.exceptions.Timeout:
            return TelemetryResult(
                status=ResultStatus.TIMEOUT,
                error=f"Prometheus query timeout after {self.timeout}s",
            )
        except Exception as e:
            logger.error(f"Prometheus query_range error: {e}")
            return TelemetryResult(
                status=ResultStatus.ERROR,
                error=str(e),
            )
    
    def get_k8s_metric(
        self,
        metric_name: str,
        namespace: str,
        duration_minutes: int = 5,
    ) -> TelemetryResult:
        """
        Get predefined Kubernetes metric.
        
        Args:
            metric_name: Metric name (cpu_usage, memory_usage, etc.)
            namespace: K8s namespace
            duration_minutes: Time range
        
        Returns:
            TelemetryResult
        """
        if metric_name not in K8S_METRICS:
            return TelemetryResult(
                status=ResultStatus.ERROR,
                error=f"Unknown metric: {metric_name}. Available: {list(K8S_METRICS.keys())}",
            )
        
        query_template = K8S_METRICS[metric_name]
        # Use string.Template for safe substitution (avoids PromQL {} conflict)
        query = Template(query_template).safe_substitute(namespace=namespace)
        
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=duration_minutes)
        
        return self.query_range(query, start, end)
    
    def check_health(self) -> bool:
        """
        Check if Prometheus is healthy.
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            url = urljoin(self.prometheus_url, "/-/healthy")
            response = requests.get(url, timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def _parse_instant_result(self, result_data: List[Dict]) -> List[MetricPoint]:
        """Parse instant query result."""
        metrics = []
        
        for item in result_data:
            metric_labels = item.get("metric", {})
            value_pair = item.get("value", [])
            
            if len(value_pair) >= 2:
                timestamp = ensure_aware(datetime.fromtimestamp(float(value_pair[0]), tz=timezone.utc))
                value = float(value_pair[1]) if value_pair[1] != "NaN" else 0.0
                
                metrics.append(MetricPoint(
                    timestamp=timestamp,
                    metric_name=metric_labels.get("__name__", "unknown"),
                    value=value,
                    labels=metric_labels,
                ))
        
        return metrics
    
    def _parse_range_result(self, result_data: List[Dict]) -> List[Dict]:
        """Parse range query result."""
        series = []
        
        for item in result_data:
            metric_labels = item.get("metric", {})
            values = item.get("values", [])
            
            data_points = []
            for value_pair in values:
                if len(value_pair) >= 2:
                    timestamp = ensure_aware(datetime.fromtimestamp(float(value_pair[0]), tz=timezone.utc))
                    value = float(value_pair[1]) if value_pair[1] != "NaN" else 0.0
                    data_points.append({
                        "timestamp": timestamp.isoformat(),
                        "value": value,
                    })
            
            series.append({
                "labels": metric_labels,
                "values": data_points,
            })
        
        return series
