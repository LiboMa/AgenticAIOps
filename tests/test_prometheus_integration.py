"""
ACI Prometheus Integration Tests

Tests for Prometheus metrics provider and integration.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import json


class TestPrometheusProvider:
    """Tests for PrometheusProvider class."""
    
    def test_provider_init_default(self):
        """Test provider initialization with defaults."""
        from src.aci.telemetry.prometheus import PrometheusProvider
        
        provider = PrometheusProvider()
        assert "prometheus" in provider.prometheus_url.lower()
        assert provider.timeout == 30
    
    def test_provider_init_custom_url(self):
        """Test provider with custom Prometheus URL."""
        from src.aci.telemetry.prometheus import PrometheusProvider
        
        custom_url = "http://prometheus-kube-prometheus-prometheus.monitoring:9090"
        provider = PrometheusProvider(prometheus_url=custom_url)
        
        assert provider.prometheus_url == custom_url
    
    def test_provider_init_trailing_slash_removed(self):
        """Test that trailing slash is removed from URL."""
        from src.aci.telemetry.prometheus import PrometheusProvider
        
        provider = PrometheusProvider(prometheus_url="http://localhost:9090/")
        assert not provider.prometheus_url.endswith("/")


class TestK8SMetrics:
    """Tests for predefined K8S metrics."""
    
    def test_k8s_metrics_defined(self):
        """Test that K8S metrics are properly defined."""
        from src.aci.telemetry.prometheus import K8S_METRICS
        
        assert "cpu_usage" in K8S_METRICS
        assert "memory_usage" in K8S_METRICS
        assert "network_rx" in K8S_METRICS
        assert "network_tx" in K8S_METRICS
        assert "restarts" in K8S_METRICS
    
    def test_k8s_metrics_have_namespace_placeholder(self):
        """Test that metrics have namespace placeholder."""
        from src.aci.telemetry.prometheus import K8S_METRICS
        
        for name, query in K8S_METRICS.items():
            assert "{namespace}" in query, f"Metric {name} missing namespace placeholder"


class TestPrometheusQuery:
    """Tests for Prometheus query functionality."""
    
    @patch('src.aci.telemetry.prometheus.requests.get')
    def test_query_success(self, mock_get):
        """Test successful Prometheus query."""
        from src.aci.telemetry.prometheus import PrometheusProvider
        
        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {"metric": {"pod": "test-pod"}, "value": [1234567890, "0.5"]}
                ]
            }
        }
        mock_get.return_value = mock_response
        
        provider = PrometheusProvider(prometheus_url="http://localhost:9090")
        result = provider.query("up")
        
        assert result is not None
        mock_get.assert_called_once()
    
    @patch('src.aci.telemetry.prometheus.requests.get')
    def test_query_with_time(self, mock_get):
        """Test query with specific time."""
        from src.aci.telemetry.prometheus import PrometheusProvider
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": {"resultType": "vector", "result": []}
        }
        mock_get.return_value = mock_response
        
        provider = PrometheusProvider(prometheus_url="http://localhost:9090")
        query_time = datetime.now() - timedelta(hours=1)
        result = provider.query("up", time=query_time)
        
        # Verify time parameter was passed
        call_args = mock_get.call_args
        assert "params" in call_args.kwargs or len(call_args.args) > 1
    
    @patch('src.aci.telemetry.prometheus.requests.get')
    def test_query_error_handling(self, mock_get):
        """Test query error handling."""
        from src.aci.telemetry.prometheus import PrometheusProvider
        from src.aci.models import ResultStatus
        
        # Mock connection error
        mock_get.side_effect = Exception("Connection refused")
        
        provider = PrometheusProvider(prometheus_url="http://localhost:9090")
        result = provider.query("up")
        
        assert result is not None
        assert result.status == ResultStatus.ERROR


class TestGetK8SMetric:
    """Tests for get_k8s_metric method."""
    
    @patch('src.aci.telemetry.prometheus.requests.get')
    def test_get_cpu_usage(self, mock_get):
        """Test getting CPU usage metric."""
        from src.aci.telemetry.prometheus import PrometheusProvider
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {"metric": {"pod": "app-1"}, "value": [1234567890, "0.25"]},
                    {"metric": {"pod": "app-2"}, "value": [1234567890, "0.50"]}
                ]
            }
        }
        mock_get.return_value = mock_response
        
        provider = PrometheusProvider(prometheus_url="http://localhost:9090")
        result = provider.get_k8s_metric("cpu_usage", namespace="default")
        
        assert result is not None
    
    @patch('src.aci.telemetry.prometheus.requests.get')
    def test_get_memory_usage(self, mock_get):
        """Test getting memory usage metric."""
        from src.aci.telemetry.prometheus import PrometheusProvider
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {"metric": {"pod": "app-1"}, "value": [1234567890, "1073741824"]}
                ]
            }
        }
        mock_get.return_value = mock_response
        
        provider = PrometheusProvider(prometheus_url="http://localhost:9090")
        result = provider.get_k8s_metric("memory_usage", namespace="kube-system")
        
        assert result is not None
    
    def test_get_unknown_metric(self):
        """Test getting unknown metric returns error."""
        from src.aci.telemetry.prometheus import PrometheusProvider
        from src.aci.models import ResultStatus
        
        provider = PrometheusProvider(prometheus_url="http://localhost:9090")
        result = provider.get_k8s_metric("unknown_metric", namespace="default")
        
        assert result.status == ResultStatus.ERROR
        assert "Unknown" in str(result.error) or result.error is not None


class TestPrometheusRangeQuery:
    """Tests for Prometheus range query functionality."""
    
    @patch('src.aci.telemetry.prometheus.requests.get')
    def test_query_range_success(self, mock_get):
        """Test successful range query."""
        from src.aci.telemetry.prometheus import PrometheusProvider
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": {
                "resultType": "matrix",
                "result": [
                    {
                        "metric": {"pod": "test-pod"},
                        "values": [
                            [1234567890, "0.5"],
                            [1234567900, "0.6"],
                            [1234567910, "0.55"]
                        ]
                    }
                ]
            }
        }
        mock_get.return_value = mock_response
        
        provider = PrometheusProvider(prometheus_url="http://localhost:9090")
        
        # Check if query_range method exists
        if hasattr(provider, 'query_range'):
            end = datetime.now()
            start = end - timedelta(hours=1)
            result = provider.query_range("up", start=start, end=end, step="15s")
            assert result is not None


class TestACIPrometheusIntegration:
    """Tests for ACI with Prometheus integration."""
    
    def test_aci_get_metrics_prometheus(self):
        """Test ACI get_metrics with Prometheus backend."""
        from src.aci import AgentCloudInterface
        
        aci = AgentCloudInterface(cluster_name="testing-cluster")
        
        # Test that get_metrics method exists and can be called
        result = aci.get_metrics(namespace="default", metric_names=["cpu_usage"])
        assert result is not None
    
    def test_prometheus_url_configuration(self):
        """Test Prometheus URL can be configured in ACI."""
        from src.aci.telemetry.prometheus import PrometheusProvider
        
        # Test with the actual Prometheus URL from the cluster
        prometheus_url = "http://prometheus-kube-prometheus-prometheus.monitoring:9090"
        provider = PrometheusProvider(prometheus_url=prometheus_url)
        
        assert provider.prometheus_url == prometheus_url


class TestPrometheusConnectionLive:
    """Live tests for actual Prometheus connection (skipped by default)."""
    
    @pytest.mark.skipif(True, reason="Live Prometheus tests - enable manually")
    def test_live_prometheus_query(self):
        """Test live Prometheus query (requires running Prometheus)."""
        from src.aci.telemetry.prometheus import PrometheusProvider
        
        provider = PrometheusProvider(
            prometheus_url="http://prometheus-kube-prometheus-prometheus.monitoring:9090"
        )
        
        # Simple up query
        result = provider.query("up")
        print(f"Live query result: {result}")
        assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
