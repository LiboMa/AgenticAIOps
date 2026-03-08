"""Alert ingestion — Channel-Driven + Events-Driven unified entry point."""

from .models import StructuredAlert, normalize_severity

__all__ = ["StructuredAlert", "normalize_severity"]
