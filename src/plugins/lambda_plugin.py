"""
Lambda Plugin - AWS Lambda function management
"""

import subprocess
import json
from typing import Dict, List, Any, Callable
from .base import PluginBase, PluginConfig, PluginStatus, PluginRegistry
import logging

logger = logging.getLogger(__name__)


class LambdaPlugin(PluginBase):
    """Plugin for managing AWS Lambda functions"""
    
    PLUGIN_TYPE = "lambda"
    PLUGIN_NAME = "AWS Lambda"
    PLUGIN_DESCRIPTION = "Monitor and manage AWS Lambda serverless functions"
    PLUGIN_ICON = "λ"
    
    def __init__(self, config: PluginConfig):
        super().__init__(config)
        self.regions = config.config.get("regions", ["ap-southeast-1"])
        self.functions: List[Dict] = []
    
    def initialize(self) -> bool:
        """Initialize Lambda plugin"""
        try:
            self._discover_functions()
            self.status = PluginStatus.ENABLED
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Lambda plugin: {e}")
            self.status = PluginStatus.ERROR
            return False
    
    def _discover_functions(self):
        """Discover Lambda functions"""
        self.functions = []
        
        for region in self.regions:
            try:
                cmd = f"aws lambda list-functions --region {region} --output json"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    for func in data.get("Functions", []):
                        self.functions.append({
                            "function_name": func.get("FunctionName"),
                            "runtime": func.get("Runtime"),
                            "memory": func.get("MemorySize"),
                            "timeout": func.get("Timeout"),
                            "region": region,
                            "last_modified": func.get("LastModified"),
                            "code_size": func.get("CodeSize"),
                        })
            except Exception as e:
                logger.warning(f"Failed to list Lambda functions in {region}: {e}")
    
    def health_check(self) -> Dict[str, Any]:
        """Check Lambda plugin health"""
        return {
            "healthy": True,
            "total_functions": len(self.functions)
        }
    
    def get_tools(self) -> List[Callable]:
        """Return Lambda-specific tools"""
        from strands import tool
        
        @tool
        def lambda_list_functions(region: str = None) -> str:
            """List Lambda functions.
            
            Args:
                region: Filter by region (optional)
            
            Returns:
                List of Lambda functions
            """
            self._discover_functions()  # Refresh
            
            functions = self.functions
            if region:
                functions = [f for f in functions if f["region"] == region]
            
            if not functions:
                return "No Lambda functions found"
            
            lines = ["Lambda Functions:", "-" * 70]
            for f in functions:
                lines.append(f"  • {f['function_name']}")
                lines.append(f"    Runtime: {f['runtime']} | Memory: {f['memory']}MB | Timeout: {f['timeout']}s")
                lines.append(f"    Region: {f['region']} | Size: {f['code_size']/1024:.1f}KB")
            
            return "\n".join(lines)
        
        @tool
        def lambda_get_function_config(function_name: str, region: str = "ap-southeast-1") -> str:
            """Get Lambda function configuration.
            
            Args:
                function_name: Name of the Lambda function
                region: AWS region
            
            Returns:
                Function configuration
            """
            try:
                cmd = f"aws lambda get-function-configuration --function-name {function_name} --region {region} --output json"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    lines = [f"Lambda Function: {function_name}", "-" * 50]
                    lines.append(f"Runtime: {data.get('Runtime')}")
                    lines.append(f"Memory: {data.get('MemorySize')}MB")
                    lines.append(f"Timeout: {data.get('Timeout')}s")
                    lines.append(f"Handler: {data.get('Handler')}")
                    lines.append(f"Role: {data.get('Role')}")
                    lines.append(f"Last Modified: {data.get('LastModified')}")
                    
                    # Environment variables (keys only for security)
                    env = data.get("Environment", {}).get("Variables", {})
                    if env:
                        lines.append(f"Environment Variables: {list(env.keys())}")
                    
                    return "\n".join(lines)
                return f"Error: {result.stderr}"
            except Exception as e:
                return f"Error: {str(e)}"
        
        @tool
        def lambda_get_invocations(function_name: str, region: str = "ap-southeast-1") -> str:
            """Get Lambda invocation metrics.
            
            Args:
                function_name: Name of the Lambda function
                region: AWS region
            
            Returns:
                Invocation metrics
            """
            try:
                cmd = f"""aws cloudwatch get-metric-statistics \\
                    --namespace AWS/Lambda \\
                    --metric-name Invocations \\
                    --dimensions Name=FunctionName,Value={function_name} \\
                    --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \\
                    --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \\
                    --period 300 \\
                    --statistics Sum \\
                    --region {region} \\
                    --output json"""
                
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    datapoints = data.get("Datapoints", [])
                    if datapoints:
                        datapoints.sort(key=lambda x: x.get("Timestamp", ""))
                        total = sum(dp.get("Sum", 0) for dp in datapoints)
                        lines = [f"Invocations for {function_name} (last hour):", "-" * 40]
                        lines.append(f"Total: {int(total)}")
                        for dp in datapoints[-5:]:
                            ts = dp.get("Timestamp", "")[:19]
                            count = int(dp.get("Sum", 0))
                            lines.append(f"  {ts}: {count}")
                        return "\n".join(lines)
                    return f"No invocation data for {function_name}"
                return f"Error: {result.stderr}"
            except Exception as e:
                return f"Error: {str(e)}"
        
        @tool
        def lambda_get_errors(function_name: str, region: str = "ap-southeast-1") -> str:
            """Get Lambda error metrics.
            
            Args:
                function_name: Name of the Lambda function
                region: AWS region
            
            Returns:
                Error metrics
            """
            try:
                cmd = f"""aws cloudwatch get-metric-statistics \\
                    --namespace AWS/Lambda \\
                    --metric-name Errors \\
                    --dimensions Name=FunctionName,Value={function_name} \\
                    --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \\
                    --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \\
                    --period 300 \\
                    --statistics Sum \\
                    --region {region} \\
                    --output json"""
                
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    datapoints = data.get("Datapoints", [])
                    total_errors = sum(dp.get("Sum", 0) for dp in datapoints)
                    
                    if total_errors > 0:
                        lines = [f"⚠️ Errors for {function_name} (last hour):", "-" * 40]
                        lines.append(f"Total Errors: {int(total_errors)}")
                        datapoints.sort(key=lambda x: x.get("Timestamp", ""))
                        for dp in datapoints[-5:]:
                            ts = dp.get("Timestamp", "")[:19]
                            count = int(dp.get("Sum", 0))
                            if count > 0:
                                lines.append(f"  {ts}: {count} errors")
                        return "\n".join(lines)
                    return f"✅ No errors for {function_name} in the last hour"
                return f"Error: {result.stderr}"
            except Exception as e:
                return f"Error: {str(e)}"
        
        return [lambda_list_functions, lambda_get_function_config, lambda_get_invocations, lambda_get_errors]
    
    def get_resources(self) -> List[Dict[str, Any]]:
        """Get list of Lambda functions"""
        return self.functions
    
    def get_status_summary(self) -> Dict[str, Any]:
        """Get Lambda status summary"""
        return {
            "plugin_type": self.PLUGIN_TYPE,
            "icon": self.PLUGIN_ICON,
            "name": self.PLUGIN_NAME,
            "total_functions": len(self.functions),
            "functions": self.functions[:10]  # Limit for UI
        }


# Register the plugin
PluginRegistry.register_plugin_class(LambdaPlugin)
