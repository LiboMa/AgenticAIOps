"""Knowledge Flywheel — RCA experience capture and retrieval.

Closes the loop: RCA result → CaseStudy → vector store → next RCA gets historical context.

Design: ADR-009 §3.5
Reference: agenticops-chat/src/agenticops/kb/
"""

from .case_study import CaseStudy, CaseStudyMeta, CaseStudyStatus, Resolution, LessonsLearned
from .vector_store import SQLiteVectorStore, VectorRecord, SearchResult
from .search import hybrid_search, HybridResult
from .flywheel import KnowledgeFlywheel

__all__ = [
    "CaseStudy",
    "CaseStudyMeta",
    "CaseStudyStatus",
    "Resolution",
    "LessonsLearned",
    "SQLiteVectorStore",
    "VectorRecord",
    "SearchResult",
    "hybrid_search",
    "HybridResult",
    "KnowledgeFlywheel",
]
