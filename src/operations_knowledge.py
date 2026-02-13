"""
Operations Knowledge Module - Learning from Incidents and Operations

This module provides:
- Incident pattern learning
- Operations knowledge accumulation  
- Pattern feedback and improvement
- Knowledge search and recommendation
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict
import hashlib

logger = logging.getLogger(__name__)


# Pattern Categories
class PatternCategory:
    PERFORMANCE = "performance"     # CPU, Memory, Latency issues
    AVAILABILITY = "availability"   # Downtime, failures
    SECURITY = "security"          # IAM, encryption, access issues
    COST = "cost"                  # Over-provisioning, unused resources
    CONFIGURATION = "configuration" # Misconfigurations


@dataclass
class IncidentRecord:
    """Record of an incident for learning"""
    incident_id: str
    title: str
    description: str
    service: str
    severity: str
    symptoms: List[str] = field(default_factory=list)
    root_cause: str = ""
    resolution: str = ""
    resolution_steps: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    start_time: str = ""
    end_time: str = ""
    resolved_by: str = "agent"
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LearnedPattern:
    """A pattern learned from incidents"""
    pattern_id: str
    title: str
    description: str
    category: str  # From PatternCategory
    service: str   # ec2, lambda, rds, etc.
    severity: str  # critical, high, medium, low
    
    # Symptoms to detect this pattern
    symptoms: List[str] = field(default_factory=list)
    symptom_keywords: List[str] = field(default_factory=list)
    
    # Resolution information
    root_cause: str = ""
    remediation: str = ""
    remediation_steps: List[str] = field(default_factory=list)
    
    # Related resources
    related_sops: List[str] = field(default_factory=list)
    related_runbooks: List[str] = field(default_factory=list)
    
    # Learning metadata
    confidence: float = 0.7
    match_count: int = 0
    success_count: int = 0
    feedback_score: float = 0.0
    
    # Timestamps
    created_at: str = ""
    updated_at: str = ""
    last_matched: str = ""
    
    # Source incidents
    source_incidents: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LearnedPattern':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class IncidentLearner:
    """
    Learn patterns from resolved incidents.
    
    Process:
    1. Analyze incident symptoms
    2. Extract root cause and resolution
    3. Check for similar existing patterns
    4. Create or improve pattern
    """
    
    def __init__(self, knowledge_store):
        self.knowledge_store = knowledge_store
    
    def learn_from_incident(self, incident: IncidentRecord) -> Optional[LearnedPattern]:
        """
        Extract a pattern from a resolved incident.
        
        Returns the learned/improved pattern.
        """
        # Extract keywords from symptoms
        symptom_keywords = self._extract_keywords(incident.symptoms + [incident.description])
        
        # Determine category
        category = self._determine_category(incident)
        
        # Check for similar existing patterns
        similar_pattern = self._find_similar_pattern(incident, symptom_keywords)
        
        if similar_pattern:
            # Improve existing pattern
            return self._improve_pattern(similar_pattern, incident)
        else:
            # Create new pattern
            return self._create_pattern(incident, category, symptom_keywords)
    
    def _extract_keywords(self, texts: List[str]) -> List[str]:
        """Extract keywords from texts for pattern matching."""
        keywords = set()
        
        # Common issue keywords
        issue_keywords = {
            'high', 'low', 'spike', 'drop', 'timeout', 'error', 'failed', 'failure',
            'slow', 'latency', 'memory', 'cpu', 'disk', 'network', 'connection',
            'unavailable', 'down', 'unreachable', 'permission', 'denied', 'exceeded',
            'throttle', 'limit', 'capacity', 'full', 'exhausted', 'leak', 'oom'
        }
        
        for text in texts:
            words = text.lower().split()
            for word in words:
                clean_word = ''.join(c for c in word if c.isalnum())
                if clean_word in issue_keywords or len(clean_word) > 5:
                    keywords.add(clean_word)
        
        return list(keywords)[:20]  # Limit to 20 keywords
    
    def _determine_category(self, incident: IncidentRecord) -> str:
        """Determine pattern category from incident."""
        text = f"{incident.title} {incident.description} {incident.root_cause}".lower()
        
        if any(k in text for k in ['cpu', 'memory', 'latency', 'slow', 'performance']):
            return PatternCategory.PERFORMANCE
        elif any(k in text for k in ['down', 'unavailable', 'failure', 'timeout']):
            return PatternCategory.AVAILABILITY
        elif any(k in text for k in ['security', 'iam', 'permission', 'access', 'encryption']):
            return PatternCategory.SECURITY
        elif any(k in text for k in ['cost', 'unused', 'oversized', 'expensive']):
            return PatternCategory.COST
        elif any(k in text for k in ['config', 'misconfigur', 'setting', 'parameter']):
            return PatternCategory.CONFIGURATION
        else:
            return PatternCategory.AVAILABILITY
    
    def _find_similar_pattern(self, incident: IncidentRecord, keywords: List[str]) -> Optional[LearnedPattern]:
        """Find similar existing pattern."""
        patterns = self.knowledge_store.search_patterns(
            service=incident.service,
            keywords=keywords,
            limit=5
        )
        
        # Check similarity threshold
        for pattern in patterns:
            overlap = len(set(keywords) & set(pattern.symptom_keywords))
            if overlap >= 3:  # At least 3 keyword overlap
                return pattern
        
        return None
    
    def _improve_pattern(self, pattern: LearnedPattern, incident: IncidentRecord) -> LearnedPattern:
        """Improve existing pattern with new incident data."""
        # Add new symptoms
        for symptom in incident.symptoms:
            if symptom not in pattern.symptoms:
                pattern.symptoms.append(symptom)
        
        # Update keywords
        new_keywords = self._extract_keywords(incident.symptoms)
        for kw in new_keywords:
            if kw not in pattern.symptom_keywords:
                pattern.symptom_keywords.append(kw)
        
        # Add resolution steps if new
        for step in incident.resolution_steps:
            if step not in pattern.remediation_steps:
                pattern.remediation_steps.append(step)
        
        # Update confidence based on consistent matches
        pattern.match_count += 1
        pattern.confidence = min(0.95, pattern.confidence + 0.05)
        
        # Track source incident
        if incident.incident_id not in pattern.source_incidents:
            pattern.source_incidents.append(incident.incident_id)
        
        pattern.updated_at = datetime.now(timezone.utc).isoformat()
        
        return pattern
    
    def _create_pattern(self, incident: IncidentRecord, category: str, keywords: List[str]) -> LearnedPattern:
        """Create new pattern from incident."""
        pattern_id = hashlib.sha256(
            f"{incident.service}:{incident.title}:{datetime.now(timezone.utc).isoformat()}".encode()
        ).hexdigest()[:12]
        
        return LearnedPattern(
            pattern_id=pattern_id,
            title=f"[Auto-learned] {incident.title}",
            description=incident.description,
            category=category,
            service=incident.service,
            severity=incident.severity,
            symptoms=incident.symptoms,
            symptom_keywords=keywords,
            root_cause=incident.root_cause,
            remediation=incident.resolution,
            remediation_steps=incident.resolution_steps,
            confidence=0.7,
            match_count=1,
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
            source_incidents=[incident.incident_id]
        )


class PatternFeedback:
    """Handle pattern feedback for improvement."""
    
    def __init__(self, knowledge_store):
        self.knowledge_store = knowledge_store
    
    def submit_feedback(self, pattern_id: str, helpful: bool, comment: str = "") -> bool:
        """Submit feedback for a pattern."""
        pattern = self.knowledge_store.get_pattern(pattern_id)
        if not pattern:
            return False
        
        # Update success count and feedback score
        if helpful:
            pattern.success_count += 1
            pattern.feedback_score = min(1.0, pattern.feedback_score + 0.1)
            pattern.confidence = min(0.95, pattern.confidence + 0.02)
        else:
            pattern.feedback_score = max(-1.0, pattern.feedback_score - 0.1)
            pattern.confidence = max(0.5, pattern.confidence - 0.05)
        
        pattern.updated_at = datetime.now(timezone.utc).isoformat()
        
        # Save updated pattern
        self.knowledge_store.save_pattern(pattern)
        
        logger.info(f"Feedback submitted for pattern {pattern_id}: helpful={helpful}")
        return True


class KnowledgeStore:
    """
    Local knowledge store with S3 sync.
    
    Provides:
    - Pattern CRUD operations
    - Search by service, category, keywords
    - S3 synchronization
    """
    
    def __init__(self, s3_bucket: str = "agentic-aiops-knowledge-base"):
        self.s3_bucket = s3_bucket
        self.patterns: Dict[str, LearnedPattern] = {}
        self._loaded = False
        
        # Try to load from S3
        self._load_from_s3()
    
    def _load_from_s3(self):
        """Load patterns from S3."""
        try:
            import boto3
            s3 = boto3.client('s3')
            
            paginator = s3.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=self.s3_bucket, Prefix='learned/'):
                for obj in page.get('Contents', []):
                    try:
                        response = s3.get_object(Bucket=self.s3_bucket, Key=obj['Key'])
                        data = json.loads(response['Body'].read().decode())
                        pattern = LearnedPattern.from_dict(data)
                        self.patterns[pattern.pattern_id] = pattern
                    except Exception as e:
                        logger.warning(f"Failed to load pattern {obj['Key']}: {e}")
            
            self._loaded = True
            logger.info(f"Loaded {len(self.patterns)} patterns from S3")
        except Exception as e:
            logger.warning(f"S3 load failed: {e}. Using empty store.")
            self._loaded = True
    
    def save_pattern(self, pattern: LearnedPattern) -> bool:
        """Save pattern to local store and S3."""
        self.patterns[pattern.pattern_id] = pattern
        
        try:
            import boto3
            s3 = boto3.client('s3')
            
            key = f"learned/{pattern.service}/{pattern.pattern_id}.json"
            s3.put_object(
                Bucket=self.s3_bucket,
                Key=key,
                Body=json.dumps(pattern.to_dict(), indent=2),
                ContentType='application/json'
            )
            logger.info(f"Pattern saved to S3: {key}")
            return True
        except Exception as e:
            logger.warning(f"S3 save failed: {e}")
            return False
    
    def get_pattern(self, pattern_id: str) -> Optional[LearnedPattern]:
        """Get pattern by ID."""
        return self.patterns.get(pattern_id)
    
    def search_patterns(
        self,
        service: Optional[str] = None,
        category: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        severity: Optional[str] = None,
        limit: int = 10
    ) -> List[LearnedPattern]:
        """Search patterns with filters."""
        results = []
        
        for pattern in self.patterns.values():
            # Apply filters
            if service and pattern.service != service:
                continue
            if category and pattern.category != category:
                continue
            if severity and pattern.severity != severity:
                continue
            
            # Keyword matching
            score = 0
            if keywords:
                overlap = len(set(keywords) & set(pattern.symptom_keywords))
                if overlap == 0:
                    continue
                score = overlap
            else:
                score = pattern.confidence
            
            results.append((score, pattern))
        
        # Sort by score descending
        results.sort(key=lambda x: x[0], reverse=True)
        
        return [p for _, p in results[:limit]]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get knowledge store statistics."""
        categories = {}
        services = {}
        
        for pattern in self.patterns.values():
            categories[pattern.category] = categories.get(pattern.category, 0) + 1
            services[pattern.service] = services.get(pattern.service, 0) + 1
        
        return {
            "total_patterns": len(self.patterns),
            "by_category": categories,
            "by_service": services,
            "avg_confidence": sum(p.confidence for p in self.patterns.values()) / max(1, len(self.patterns)),
        }


# Singleton instances
_knowledge_store: Optional[KnowledgeStore] = None
_incident_learner: Optional[IncidentLearner] = None
_feedback_handler: Optional[PatternFeedback] = None


def get_knowledge_store() -> KnowledgeStore:
    """Get or create knowledge store instance."""
    global _knowledge_store
    if _knowledge_store is None:
        _knowledge_store = KnowledgeStore()
    return _knowledge_store


def get_incident_learner() -> IncidentLearner:
    """Get or create incident learner instance."""
    global _incident_learner
    if _incident_learner is None:
        _incident_learner = IncidentLearner(get_knowledge_store())
    return _incident_learner


def get_feedback_handler() -> PatternFeedback:
    """Get or create feedback handler instance."""
    global _feedback_handler
    if _feedback_handler is None:
        _feedback_handler = PatternFeedback(get_knowledge_store())
    return _feedback_handler
