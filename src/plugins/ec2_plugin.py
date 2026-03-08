"""
EC2 Plugin - EC2 instance management
"""

import subprocess
import json
from typing import Dict, List, Any, Callable, Optional
from .base import PluginBase, PluginConfig, PluginStatus, PluginRegistry, ClusterConfig
import logging

logger = logging.getLogger(__name__)


class EC2Plugin(PluginBase):
    """Plugin for managing EC2 instances"""
    
    PLUGIN_TYPE = "ec2"
    PLUGIN_NAME = "Amazon EC2"
    PLUGIN_DESCRIPTION = "Monitor and manage Amazon EC2 instances"
    PLUGIN_ICON = "🖥️"
    
    def __init__(self, config: PluginConfig):
        super().__init__(config)
        self.regions = config.config.get("regions", ["ap-southeast-1"])
        self.instances: List[Dict] = []
    
    def initialize(self) -> bool:
        """Initialize EC2 plugin"""
        try:
            self._discover_instances()
            self.status = PluginStatus.ENABLED
            return True
        except Exception as e:
            logger.error(f"Failed to initialize EC2 plugin: {e}")
            self.status = PluginStatus.ERROR
            return False
    
    def _discover_instances(self):
        """Discover EC2 instances"""
        self.instances = []
        
        for region in self.regions:
            try:
                cmd = f"aws ec2 describe-instances --region {region} --output json"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    for reservation in data.get("Reservations", []):
                        for instance in reservation.get("Instances", []):
                            instance_id = instance.get("InstanceId")
                            name = "unnamed"
                            for tag in instance.get("Tags", []):
                                if tag.get("Key") == "Name":
                                    name = tag.get("Value")
                                    break
                            
                            self.instances.append({
                                "instance_id": instance_id,
                                "name": name,
                                "region": region,
                                "state": instance.get("State", {}).get("Name"),
                                "type": instance.get("InstanceType"),
                                "private_ip": instance.get("PrivateIpAddress"),
                                "public_ip": instance.get("PublicIpAddress"),
                            })
            except Exception as e:
                logger.warning(f"Failed to list EC2 instances in {region}: {e}")
    
    def health_check(self) -> Dict[str, Any]:
        """Check EC2 plugin health"""
        running = sum(1 for i in self.instances if i.get("state") == "running")
        return {
            "healthy": True,
            "total_instances": len(self.instances),
            "running_instances": running,
            "stopped_instances": len(self.instances) - running
        }
    
    def get_tools(self) -> List[Callable]:
        """Return EC2-specific tools"""
        from strands import tool
        
        @tool
        def ec2_list_instances(region: str = None, state: str = None) -> str:
            """List EC2 instances.
            
            Args:
                region: Filter by region (optional)
                state: Filter by state (running, stopped, etc.)
            
            Returns:
                List of EC2 instances
            """
            self._discover_instances()  # Refresh
            
            instances = self.instances
            if region:
                instances = [i for i in instances if i["region"] == region]
            if state:
                instances = [i for i in instances if i["state"] == state]
            
            if not instances:
                return "No EC2 instances found matching criteria"
            
            lines = ["EC2 Instances:", "-" * 80]
            for i in instances:
                lines.append(f"  • {i['name']} ({i['instance_id']})")
                lines.append(f"    Region: {i['region']} | Type: {i['type']} | State: {i['state']}")
                lines.append(f"    Private IP: {i['private_ip']} | Public IP: {i.get('public_ip', 'N/A')}")
            
            return "\n".join(lines)
        
        @tool
        def ec2_get_instance_status(instance_id: str) -> str:
            """Get detailed status of an EC2 instance.
            
            Args:
                instance_id: The EC2 instance ID
            
            Returns:
                Instance status details
            """
            try:
                # Find region for instance
                region = None
                for i in self.instances:
                    if i["instance_id"] == instance_id:
                        region = i["region"]
                        break
                
                if not region:
                    region = "ap-southeast-1"  # Default
                
                cmd = f"aws ec2 describe-instance-status --instance-ids {instance_id} --region {region} --output json"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    statuses = data.get("InstanceStatuses", [])
                    if statuses:
                        status = statuses[0]
                        return json.dumps(status, indent=2)
                    return f"Instance {instance_id} status not available (may be stopped)"
                return f"Error: {result.stderr}"
            except Exception as e:
                return f"Error: {str(e)}"
        
        @tool
        def ec2_get_metrics(instance_id: str, metric: str = "CPUUtilization", period: int = 300) -> str:
            """Get CloudWatch metrics for an EC2 instance.
            
            Args:
                instance_id: The EC2 instance ID
                metric: Metric name (CPUUtilization, NetworkIn, NetworkOut, etc.)
                period: Period in seconds (default: 300)
            
            Returns:
                Metric data
            """
            try:
                # Find region
                region = "ap-southeast-1"
                for i in self.instances:
                    if i["instance_id"] == instance_id:
                        region = i["region"]
                        break
                
                cmd = f"""aws cloudwatch get-metric-statistics \\
                    --namespace AWS/EC2 \\
                    --metric-name {metric} \\
                    --dimensions Name=InstanceId,Value={instance_id} \\
                    --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \\
                    --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \\
                    --period {period} \\
                    --statistics Average \\
                    --region {region} \\
                    --output json"""
                
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    datapoints = data.get("Datapoints", [])
                    if datapoints:
                        # Sort by timestamp
                        datapoints.sort(key=lambda x: x.get("Timestamp", ""))
                        lines = [f"{metric} for {instance_id}:", "-" * 40]
                        for dp in datapoints[-5:]:  # Last 5 data points
                            ts = dp.get("Timestamp", "")[:19]
                            avg = dp.get("Average", 0)
                            lines.append(f"  {ts}: {avg:.2f}")
                        return "\n".join(lines)
                    return f"No {metric} data available for {instance_id}"
                return f"Error: {result.stderr}"
            except Exception as e:
                return f"Error: {str(e)}"
        
        return [ec2_list_instances, ec2_get_instance_status, ec2_get_metrics]
    
    def get_resources(self) -> List[Dict[str, Any]]:
        """Get list of EC2 instances"""
        return self.instances
    
    def get_status_summary(self) -> Dict[str, Any]:
        """Get EC2 status summary"""
        health = self.health_check()
        return {
            "plugin_type": self.PLUGIN_TYPE,
            "icon": self.PLUGIN_ICON,
            "name": self.PLUGIN_NAME,
            "total_instances": health["total_instances"],
            "running": health["running_instances"],
            "stopped": health["stopped_instances"],
            "instances": self.instances[:10]  # Limit for UI
        }


# Register the plugin
PluginRegistry.register_plugin_class(EC2Plugin)
