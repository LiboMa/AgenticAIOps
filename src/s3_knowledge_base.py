"""
S3 Knowledge Base for Pattern Storage

This module provides:
- Store anomaly patterns in S3
- Pattern matching for RCA
- Agent + MCP filtering (quality control)

Design: Agent filters patterns before storage to ensure high quality.
"""

import json
import logging
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

# S3 Configuration
S3_BUCKET_NAME = "agentic-aiops-knowledge-base"
S3_PREFIX = "patterns/"


@dataclass
class AnomalyPattern:
    """An anomaly pattern for the knowledge base"""
    pattern_id: str
    title: str
    description: str
    resource_type: str  # ec2, lambda, s3, rds, iam, etc.
    severity: str  # critical, high, medium, low
    symptoms: List[str] = field(default_factory=list)
    root_cause: str = ""
    remediation: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    confidence: float = 0.8
    created_at: str = ""
    updated_at: str = ""
    source: str = "agent"  # agent, manual, imported
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AnomalyPattern':
        return cls(**data)


@dataclass 
class RCAResult:
    """Root Cause Analysis result"""
    issue_id: str
    matched_pattern: Optional[AnomalyPattern]
    confidence: float
    analysis: str
    recommendations: List[str]
    timestamp: str


class S3KnowledgeBase:
    """
    S3-based Knowledge Base for anomaly patterns
    
    Features:
    - Store patterns with Agent quality filtering
    - Pattern matching for RCA
    - Local cache for performance
    """
    
    def __init__(self, bucket_name: str = S3_BUCKET_NAME):
        self.bucket_name = bucket_name
        self.prefix = S3_PREFIX
        self.s3_client = None
        self._local_cache: Dict[str, AnomalyPattern] = {}
        self._cache_loaded = False
        
        # Initialize S3 client
        self._init_s3_client()
        
    def _init_s3_client(self):
        """Initialize S3 client"""
        try:
            import boto3
            self.s3_client = boto3.client('s3')
            logger.info(f"S3 client initialized for bucket: {self.bucket_name}")
        except Exception as e:
            logger.warning(f"S3 client init failed: {e}. Using local storage only.")
            self.s3_client = None
    
    def _generate_pattern_id(self, pattern: AnomalyPattern) -> str:
        """Generate unique pattern ID"""
        content = f"{pattern.resource_type}:{pattern.title}:{pattern.description}"
        return hashlib.sha256(content.encode()).hexdigest()[:12]
    
    async def add_pattern(self, pattern: AnomalyPattern, quality_score: float = 0.0) -> bool:
        """
        Add a pattern to the knowledge base.
        
        Agent + MCP filtering: Only add patterns with quality_score >= 0.7
        """
        # Quality gate - Agent filtering
        if quality_score < 0.7:
            logger.info(f"Pattern rejected: quality score {quality_score} < 0.7")
            return False
        
        # Generate ID if not set
        if not pattern.pattern_id:
            pattern.pattern_id = self._generate_pattern_id(pattern)
        
        # Set timestamps
        now = datetime.now(timezone.utc).isoformat()
        if not pattern.created_at:
            pattern.created_at = now
        pattern.updated_at = now
        
        # Store in S3
        success = await self._store_to_s3(pattern)
        
        # Update local cache
        self._local_cache[pattern.pattern_id] = pattern
        
        logger.info(f"Pattern added: {pattern.pattern_id} - {pattern.title}")
        return success
    
    async def _store_to_s3(self, pattern: AnomalyPattern) -> bool:
        """Store pattern to S3"""
        if not self.s3_client:
            logger.warning("S3 client not available, storing locally only")
            return True
        
        try:
            key = f"{self.prefix}{pattern.resource_type}/{pattern.pattern_id}.json"
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=json.dumps(pattern.to_dict(), indent=2),
                ContentType='application/json'
            )
            logger.info(f"Pattern stored to S3: {key}")
            return True
        except Exception as e:
            logger.error(f"S3 store failed: {e}")
            return False
    
    async def get_pattern(self, pattern_id: str) -> Optional[AnomalyPattern]:
        """Get a pattern by ID"""
        # Check local cache first
        if pattern_id in self._local_cache:
            return self._local_cache[pattern_id]
        
        # Try to load from S3
        if not self._cache_loaded:
            await self._load_cache()
        
        return self._local_cache.get(pattern_id)
    
    async def _load_cache(self):
        """Load all patterns from S3 into local cache"""
        if not self.s3_client:
            self._cache_loaded = True
            return
        
        try:
            paginator = self.s3_client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=self.prefix):
                for obj in page.get('Contents', []):
                    key = obj['Key']
                    if key.endswith('.json'):
                        response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
                        data = json.loads(response['Body'].read().decode())
                        pattern = AnomalyPattern.from_dict(data)
                        self._local_cache[pattern.pattern_id] = pattern
            
            logger.info(f"Loaded {len(self._local_cache)} patterns from S3")
        except Exception as e:
            logger.warning(f"Failed to load from S3: {e}")
        
        self._cache_loaded = True
    
    async def search_patterns(
        self,
        resource_type: Optional[str] = None,
        severity: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        limit: int = 10
    ) -> List[AnomalyPattern]:
        """Search patterns by criteria"""
        if not self._cache_loaded:
            await self._load_cache()
        
        results = []
        for pattern in self._local_cache.values():
            # Filter by resource type
            if resource_type and pattern.resource_type != resource_type:
                continue
            
            # Filter by severity
            if severity and pattern.severity != severity:
                continue
            
            # Filter by keywords (in title, description, symptoms)
            if keywords:
                pattern_text = f"{pattern.title} {pattern.description} {' '.join(pattern.symptoms)}"
                if not any(kw.lower() in pattern_text.lower() for kw in keywords):
                    continue
            
            results.append(pattern)
            
            if len(results) >= limit:
                break
        
        return results
    
    async def match_pattern(self, issue: Dict[str, Any]) -> RCAResult:
        """
        Match an issue to a pattern for RCA.
        
        Uses symptom matching and confidence scoring.
        """
        resource_type = issue.get('resource_type', '')
        title = issue.get('title', '')
        description = issue.get('description', '')
        
        # Search for matching patterns
        patterns = await self.search_patterns(
            resource_type=resource_type,
            keywords=title.split()[:3]  # Use first 3 words as keywords
        )
        
        if not patterns:
            # No match found
            return RCAResult(
                issue_id=issue.get('id', 'unknown'),
                matched_pattern=None,
                confidence=0.0,
                analysis="No matching pattern found in knowledge base.",
                recommendations=["Manual investigation required."],
                timestamp=datetime.now(timezone.utc).isoformat()
            )
        
        # Score patterns
        best_pattern = None
        best_score = 0.0
        
        for pattern in patterns:
            score = self._calculate_match_score(issue, pattern)
            if score > best_score:
                best_score = score
                best_pattern = pattern
        
        if best_pattern and best_score >= 0.5:
            return RCAResult(
                issue_id=issue.get('id', 'unknown'),
                matched_pattern=best_pattern,
                confidence=best_score,
                analysis=f"Matched pattern: {best_pattern.title}\n\nRoot cause: {best_pattern.root_cause}",
                recommendations=[best_pattern.remediation] if best_pattern.remediation else [],
                timestamp=datetime.now(timezone.utc).isoformat()
            )
        
        return RCAResult(
            issue_id=issue.get('id', 'unknown'),
            matched_pattern=None,
            confidence=best_score,
            analysis="No high-confidence match found.",
            recommendations=["Review manually and consider adding to knowledge base."],
            timestamp=datetime.now(timezone.utc).isoformat()
        )
    
    def _calculate_match_score(self, issue: Dict[str, Any], pattern: AnomalyPattern) -> float:
        """Calculate match score between issue and pattern"""
        score = 0.0
        
        # Resource type match (0.3 weight)
        if issue.get('resource_type') == pattern.resource_type:
            score += 0.3
        
        # Title similarity (0.3 weight)
        issue_words = set(issue.get('title', '').lower().split())
        pattern_words = set(pattern.title.lower().split())
        if issue_words and pattern_words:
            overlap = len(issue_words & pattern_words) / len(issue_words | pattern_words)
            score += 0.3 * overlap
        
        # Symptom matching (0.4 weight)
        issue_desc = issue.get('description', '').lower()
        matched_symptoms = sum(1 for s in pattern.symptoms if s.lower() in issue_desc)
        if pattern.symptoms:
            score += 0.4 * (matched_symptoms / len(pattern.symptoms))
        
        return min(score * pattern.confidence, 1.0)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get knowledge base statistics"""
        stats = {
            "total_patterns": len(self._local_cache),
            "by_resource_type": {},
            "by_severity": {},
            "cache_loaded": self._cache_loaded,
            "s3_available": self.s3_client is not None,
        }
        
        for pattern in self._local_cache.values():
            # Count by resource type
            rt = pattern.resource_type
            stats["by_resource_type"][rt] = stats["by_resource_type"].get(rt, 0) + 1
            
            # Count by severity
            sev = pattern.severity
            stats["by_severity"][sev] = stats["by_severity"].get(sev, 0) + 1
        
        return stats


# Default patterns to seed the knowledge base
DEFAULT_PATTERNS = [
    AnomalyPattern(
        pattern_id="ec2_high_cpu",
        title="EC2 High CPU Utilization",
        description="EC2 instance showing sustained high CPU usage above 80%",
        resource_type="ec2",
        severity="high",
        symptoms=["high cpu", "cpu utilization", "cpu above 80", "performance degradation"],
        root_cause="Instance is under heavy load. Could be: 1) Increased traffic, 2) Inefficient code, 3) Resource-intensive process, 4) Cryptocurrency mining malware",
        remediation="1) Scale up instance type, 2) Add more instances with auto-scaling, 3) Investigate and optimize workload, 4) Run security scan if unexpected",
        tags=["ec2", "cpu", "performance"],
        confidence=0.9,
    ),
    AnomalyPattern(
        pattern_id="s3_public_bucket",
        title="S3 Public Bucket Access",
        description="S3 bucket has public access enabled",
        resource_type="s3",
        severity="critical",
        symptoms=["public access", "bucket policy", "public bucket", "acl public"],
        root_cause="Bucket policy or ACL allows public access. This may expose sensitive data to the internet.",
        remediation="1) Review bucket policy, 2) Disable public access unless required, 3) Use CloudFront for public content, 4) Enable S3 Block Public Access",
        tags=["s3", "security", "public-access"],
        confidence=0.95,
    ),
    AnomalyPattern(
        pattern_id="iam_root_mfa",
        title="Root Account MFA Not Enabled",
        description="AWS root account does not have MFA enabled",
        resource_type="iam",
        severity="critical",
        symptoms=["root account", "mfa disabled", "no mfa", "root mfa"],
        root_cause="Root account without MFA is a critical security risk. Root has full access to all AWS resources.",
        remediation="1) Enable MFA on root account immediately, 2) Use hardware MFA for highest security, 3) Minimize root account usage",
        tags=["iam", "security", "mfa", "root"],
        confidence=0.98,
    ),
    AnomalyPattern(
        pattern_id="ec2_sg_open_ssh",
        title="Security Group Allows SSH from Anywhere",
        description="Security group has port 22 (SSH) open to 0.0.0.0/0",
        resource_type="ec2",
        severity="critical",
        symptoms=["security group", "port 22", "ssh open", "0.0.0.0/0", "open to internet"],
        root_cause="Security group allows SSH access from any IP address. This exposes the instance to brute force attacks.",
        remediation="1) Restrict SSH to specific IPs or CIDR ranges, 2) Use AWS Systems Manager Session Manager instead, 3) Use a bastion host, 4) Enable fail2ban on instances",
        tags=["ec2", "security", "ssh", "security-group"],
        confidence=0.95,
    ),
    AnomalyPattern(
        pattern_id="lambda_deprecated_runtime",
        title="Lambda Using Deprecated Runtime",
        description="Lambda function is using a deprecated or soon-to-be-deprecated runtime",
        resource_type="lambda",
        severity="medium",
        symptoms=["deprecated runtime", "python 2.7", "nodejs 8", "old runtime"],
        root_cause="Lambda function uses a runtime that is or will be deprecated. AWS will eventually block updates to these functions.",
        remediation="1) Update function code for newer runtime, 2) Test thoroughly before deployment, 3) Schedule migration before deprecation date",
        tags=["lambda", "runtime", "deprecated"],
        confidence=0.85,
    ),
    AnomalyPattern(
        pattern_id="rds_public_access",
        title="RDS Instance Publicly Accessible",
        description="RDS database instance has public accessibility enabled",
        resource_type="rds",
        severity="critical",
        symptoms=["publicly accessible", "public rds", "database exposed"],
        root_cause="RDS instance is accessible from the internet. This may expose sensitive data and increase attack surface.",
        remediation="1) Disable public accessibility, 2) Use VPC peering or PrivateLink for cross-account access, 3) Use security groups to restrict access, 4) Review connection logs",
        tags=["rds", "security", "public-access"],
        confidence=0.92,
    ),
]


# Singleton instance
_knowledge_base: Optional[S3KnowledgeBase] = None


async def get_knowledge_base() -> S3KnowledgeBase:
    """Get or create the knowledge base singleton"""
    global _knowledge_base
    if _knowledge_base is None:
        _knowledge_base = S3KnowledgeBase()
        # Seed with default patterns
        for pattern in DEFAULT_PATTERNS:
            await _knowledge_base.add_pattern(pattern, quality_score=1.0)
        logger.info(f"Knowledge base initialized with {len(DEFAULT_PATTERNS)} default patterns")
    return _knowledge_base
