"""
Runbook Loader

Loads and parses runbook definitions from YAML files.
"""

import logging
from pathlib import Path
from typing import List, Optional, Dict

import yaml

from .models import Runbook, RunbookStep

logger = logging.getLogger(__name__)

# Default runbook directory
DEFAULT_RUNBOOK_DIR = Path(__file__).parent.parent.parent / "config" / "runbooks"


class RunbookLoader:
    """
    Loads runbooks from YAML configuration files.
    
    Example:
        loader = RunbookLoader()
        
        # Load all runbooks
        runbooks = loader.load_all()
        
        # Get runbook for a pattern
        runbook = loader.get_for_pattern("oom-001")
    """
    
    def __init__(self, runbook_dir: Optional[str] = None):
        """
        Initialize the loader.
        
        Args:
            runbook_dir: Directory containing runbook YAML files
        """
        self.runbook_dir = Path(runbook_dir) if runbook_dir else DEFAULT_RUNBOOK_DIR
        self._runbooks: Dict[str, Runbook] = {}
        self._pattern_mapping: Dict[str, str] = {}  # pattern_id -> runbook_id
        
        if self.runbook_dir.exists():
            self.load_all()
    
    def load_all(self) -> List[Runbook]:
        """
        Load all runbooks from the directory.
        
        Returns:
            List of loaded runbooks
        """
        self._runbooks.clear()
        self._pattern_mapping.clear()
        
        if not self.runbook_dir.exists():
            logger.warning(f"Runbook directory not found: {self.runbook_dir}")
            return []
        
        runbooks = []
        
        for yaml_file in self.runbook_dir.glob("*.yaml"):
            try:
                runbook = self._load_file(yaml_file)
                if runbook:
                    self._runbooks[runbook.id] = runbook
                    runbooks.append(runbook)
                    
                    # Build pattern mapping
                    for trigger in runbook.triggers:
                        if 'pattern_id' in trigger:
                            self._pattern_mapping[trigger['pattern_id']] = runbook.id
                    
                    logger.info(f"Loaded runbook: {runbook.id} from {yaml_file.name}")
                    
            except Exception as e:
                logger.error(f"Failed to load runbook {yaml_file}: {e}")
        
        logger.info(f"Loaded {len(runbooks)} runbooks")
        return runbooks
    
    def _load_file(self, file_path: Path) -> Optional[Runbook]:
        """Load a single runbook file."""
        with open(file_path, 'r') as f:
            data = yaml.safe_load(f)
        
        if not data or 'id' not in data:
            return None
        
        # Parse steps
        steps = []
        for step_data in data.get('steps', []):
            steps.append(RunbookStep(
                id=step_data.get('id', ''),
                action=step_data.get('action', ''),
                description=step_data.get('description', ''),
                params=step_data.get('params', {}),
                output=step_data.get('output'),
                requires_approval=step_data.get('requires_approval', False),
                timeout_seconds=step_data.get('timeout_seconds', 300),
                retry_count=step_data.get('retry_count', 0),
            ))
        
        # Parse rollback steps
        rollback = []
        for step_data in data.get('rollback', []):
            rollback.append(RunbookStep(
                id=step_data.get('id', ''),
                action=step_data.get('action', ''),
                description=step_data.get('description', ''),
                params=step_data.get('params', {}),
            ))
        
        return Runbook(
            id=data['id'],
            name=data.get('name', data['id']),
            description=data.get('description', ''),
            triggers=data.get('triggers', []),
            preconditions=data.get('preconditions', []),
            steps=steps,
            rollback=rollback,
            notifications=data.get('notifications', {}),
        )
    
    def get(self, runbook_id: str) -> Optional[Runbook]:
        """Get a runbook by ID."""
        return self._runbooks.get(runbook_id)
    
    def get_for_pattern(self, pattern_id: str) -> Optional[Runbook]:
        """Get the runbook for a specific pattern."""
        runbook_id = self._pattern_mapping.get(pattern_id)
        if runbook_id:
            return self._runbooks.get(runbook_id)
        return None
    
    def list_runbooks(self) -> List[Dict]:
        """List all loaded runbooks."""
        return [rb.to_dict() for rb in self._runbooks.values()]
    
    def reload(self) -> None:
        """Reload all runbooks."""
        self.load_all()
