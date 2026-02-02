"""
Fault Injection Scripts

Provides fault injection capabilities for testing AgenticAIOps diagnosis.
Based on AIOpsLab framework.
"""

from .inject_oom import inject_oom, cleanup as cleanup_oom
from .inject_image_error import inject_image_error, cleanup as cleanup_image
from .inject_cpu import inject_cpu_throttling, cleanup as cleanup_cpu
from .inject_service_error import inject_service_error, cleanup as cleanup_service

__all__ = [
    "inject_oom",
    "inject_image_error", 
    "inject_cpu_throttling",
    "inject_service_error",
    "cleanup_oom",
    "cleanup_image",
    "cleanup_cpu",
    "cleanup_service",
]
