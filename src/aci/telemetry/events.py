"""
ACI Events Provider

Provides Kubernetes events retrieval.
"""

import json
import logging
import subprocess
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from ..models import TelemetryResult, ResultStatus, EventEntry
from ...utils.time import ensure_aware

logger = logging.getLogger(__name__)


class EventsProvider:
    """
    Kubernetes events provider.
    
    Uses kubectl get events for event retrieval.
    """
    
    def __init__(self, cluster_name: str, region: str):
        self.cluster_name = cluster_name
        self.region = region
    
    def get_events(
        self,
        namespace: str = "all",
        event_type: Optional[str] = None,
        reason: Optional[str] = None,
        involved_object: Optional[str] = None,
        duration_minutes: int = 60,
        limit: int = 50,
    ) -> TelemetryResult:
        """
        Get Kubernetes events.
        
        Args:
            namespace: Namespace ("all" for all namespaces)
            event_type: Event type (Normal, Warning)
            reason: Event reason (BackOff, OOMKilled, etc.)
            involved_object: Related object name
            duration_minutes: Time range
            limit: Max entries
        
        Returns:
            TelemetryResult with EventEntry list
        """
        try:
            # Build kubectl command
            cmd = ["kubectl", "get", "events", "-o", "json"]
            
            if namespace == "all":
                cmd.append("--all-namespaces")
            else:
                cmd.extend(["-n", namespace])
            
            # Execute command
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                logger.warning(f"kubectl get events failed: {result.stderr}")
                return TelemetryResult(
                    status=ResultStatus.ERROR,
                    error=result.stderr,
                )
            
            # Parse JSON output
            events_data = json.loads(result.stdout)
            events: List[EventEntry] = []
            
            cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=duration_minutes)
            
            for item in events_data.get("items", []):
                event = self._parse_event(item)
                if not event:
                    continue
                
                # Apply filters
                if event.timestamp < cutoff_time:
                    continue
                
                if event_type and event.event_type.lower() != event_type.lower():
                    continue
                
                if reason and reason.lower() not in event.reason.lower():
                    continue
                
                if involved_object and involved_object.lower() not in event.involved_object.lower():
                    continue
                
                events.append(event)
            
            # Sort by timestamp (newest first) and limit
            events.sort(key=lambda x: x.timestamp, reverse=True)
            events = events[:limit]
            
            # Count by type
            warning_count = sum(1 for e in events if e.event_type == "Warning")
            normal_count = sum(1 for e in events if e.event_type == "Normal")
            
            return TelemetryResult(
                status=ResultStatus.SUCCESS,
                data=[event.to_dict() for event in events],
                metadata={
                    "namespace": namespace,
                    "total_events": len(events),
                    "warning_count": warning_count,
                    "normal_count": normal_count,
                    "duration_minutes": duration_minutes,
                },
            )
            
        except subprocess.TimeoutExpired:
            logger.error("kubectl get events timeout")
            return TelemetryResult(
                status=ResultStatus.TIMEOUT,
                error="kubectl get events timeout",
            )
        except Exception as e:
            logger.error(f"Error getting events: {e}")
            return TelemetryResult(
                status=ResultStatus.ERROR,
                error=str(e),
            )
    
    def _parse_event(self, item: dict) -> Optional[EventEntry]:
        """Parse a Kubernetes event item."""
        try:
            metadata = item.get("metadata", {})
            involved_obj = item.get("involvedObject", {})
            
            # Parse timestamp
            last_timestamp = item.get("lastTimestamp") or item.get("eventTime") or metadata.get("creationTimestamp")
            if not last_timestamp:
                return None
            
            # Handle different timestamp formats
            timestamp_str = last_timestamp.replace("Z", "+00:00")
            if "." in timestamp_str:
                timestamp_str = timestamp_str.split(".")[0] + "+00:00"
            
            timestamp = ensure_aware(datetime.fromisoformat(timestamp_str))
            
            return EventEntry(
                timestamp=timestamp,
                namespace=metadata.get("namespace", "unknown"),
                event_type=item.get("type", "Unknown"),
                reason=item.get("reason", "Unknown"),
                message=item.get("message", ""),
                involved_object=involved_obj.get("name", "unknown"),
                involved_kind=involved_obj.get("kind", "unknown"),
                count=item.get("count", 1),
            )
            
        except Exception as e:
            logger.debug(f"Failed to parse event: {e}")
            return None
