"""Router: /api/knowledge, /api/vector, /api/kb, /api/sop - Knowledge & SOP APIs."""

from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException

from routers.schemas import (
    IncidentLearnRequest, FeedbackRequest,
    SOPSuggestRequest, SOPExecuteRequest,
    VectorIndexRequest, SemanticSearchRequest,
    PatternAddRequest, RCARequest,
)

router = APIRouter(tags=["knowledge"])


# =============================================================================
# Operations Knowledge
# =============================================================================

@router.get("/api/knowledge/stats")
async def get_ops_knowledge_stats():
    """Get operations knowledge statistics."""
    try:
        from src.knowledge_search import get_knowledge_store
        store = get_knowledge_store()
        return store.get_stats()
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/knowledge/patterns")
async def list_ops_patterns(
    service: Optional[str] = None,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50
):
    """List learned patterns."""
    try:
        from src.knowledge_search import get_knowledge_store
        store = get_knowledge_store()
        patterns = store.search_patterns(
            service=service,
            category=category,
            severity=severity,
            limit=limit
        )
        return {
            "patterns": [p.to_dict() for p in patterns],
            "count": len(patterns)
        }
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/knowledge/search")
async def search_ops_knowledge(request: Dict[str, Any]):
    """Search operations knowledge base."""
    try:
        from src.knowledge_search import get_knowledge_store
        store = get_knowledge_store()

        keywords = request.get('keywords', [])
        if isinstance(keywords, str):
            keywords = keywords.split()

        patterns = store.search_patterns(
            service=request.get('service'),
            category=request.get('category'),
            keywords=keywords,
            limit=request.get('limit', 10)
        )
        return {
            "patterns": [p.to_dict() for p in patterns],
            "count": len(patterns)
        }
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/knowledge/learn")
async def learn_from_incident(request: IncidentLearnRequest):
    """Learn pattern from a resolved incident."""
    try:
        from src.knowledge_search import get_incident_learner, IncidentRecord
        learner = get_incident_learner()

        incident = IncidentRecord(
            incident_id=request.incident_id,
            title=request.title,
            description=request.description,
            service=request.service,
            severity=request.severity,
            symptoms=request.symptoms,
            root_cause=request.root_cause,
            resolution=request.resolution,
            resolution_steps=request.resolution_steps
        )

        pattern = learner.learn_from_incident(incident)

        if pattern:
            from src.knowledge_search import get_knowledge_store
            store = get_knowledge_store()
            store.save_pattern(pattern)

            return {
                "success": True,
                "pattern_id": pattern.pattern_id,
                "title": pattern.title,
                "confidence": pattern.confidence,
                "is_new": len(pattern.source_incidents) == 1
            }
        else:
            return {"success": False, "error": "Failed to learn pattern"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/knowledge/feedback")
async def submit_pattern_feedback(request: FeedbackRequest):
    """Submit feedback for a pattern."""
    try:
        from src.knowledge_search import get_feedback_handler
        handler = get_feedback_handler()

        success = handler.submit_feedback(
            request.pattern_id,
            request.helpful,
            request.comment
        )

        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# SOP System APIs
# =============================================================================

@router.get("/api/sop/list")
async def list_sops(
    service: Optional[str] = None,
    category: Optional[str] = None,
    severity: Optional[str] = None
):
    """List available SOPs."""
    try:
        from src.sop_system import get_sop_store
        store = get_sop_store()
        sops = store.list_sops(service=service, category=category, severity=severity)
        return {
            "sops": [s.to_dict() for s in sops],
            "count": len(sops)
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/sop/{sop_id}")
async def get_sop(sop_id: str):
    """Get SOP details."""
    try:
        from src.sop_system import get_sop_store
        store = get_sop_store()
        sop = store.get_sop(sop_id)
        if not sop:
            return {"error": f"SOP {sop_id} not found"}
        return sop.to_dict()
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/sop/suggest")
async def suggest_sops(request: SOPSuggestRequest):
    """Suggest SOPs for an issue."""
    try:
        from src.sop_system import get_sop_store
        store = get_sop_store()
        suggested = store.suggest_sops(
            request.service,
            request.keywords,
            request.severity
        )
        return {
            "suggestions": [s.to_dict() for s in suggested],
            "count": len(suggested)
        }
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/sop/execute")
async def execute_sop(request: SOPExecuteRequest):
    """Start executing an SOP."""
    try:
        from src.sop_system import get_sop_executor
        executor = get_sop_executor()

        execution = executor.start_execution(
            request.sop_id,
            request.triggered_by,
            request.context
        )

        if not execution:
            return {"success": False, "error": "SOP not found or execution failed"}

        return {
            "success": True,
            "execution_id": execution.execution_id,
            "status": execution.status
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/sop/execution/{execution_id}")
async def get_sop_execution(execution_id: str):
    """Get SOP execution status."""
    try:
        from src.sop_system import get_sop_executor
        executor = get_sop_executor()

        execution = executor.get_execution(execution_id)
        if not execution:
            return {"error": "Execution not found"}

        return execution.to_dict()
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# Vector Search APIs
# =============================================================================

@router.get("/api/vector/stats")
async def get_vector_stats():
    """Get vector search index statistics."""
    try:
        from src.vector_search import get_vector_search
        search = get_vector_search()
        return search.get_stats()
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/vector/index/create")
async def create_vector_index():
    """Create the knowledge vector index."""
    try:
        from src.vector_search import get_vector_search
        search = get_vector_search()
        success = search.create_index()
        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/vector/index")
async def index_document(request: VectorIndexRequest):
    """Index a document with embeddings."""
    try:
        from src.vector_search import get_vector_search
        search = get_vector_search()

        success = search.index_knowledge(
            doc_id=request.doc_id,
            title=request.title,
            description=request.description,
            content=request.content,
            doc_type=request.doc_type,
            category=request.category,
            service=request.service,
            severity=request.severity,
            tags=request.tags
        )
        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/vector/search")
async def semantic_search(request: SemanticSearchRequest):
    """Semantic search using vector similarity."""
    try:
        from src.vector_search import get_vector_search
        search = get_vector_search()

        results = search.semantic_search(
            query=request.query,
            doc_type=request.doc_type,
            service=request.service,
            limit=request.limit
        )
        return {"results": results, "count": len(results)}
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/vector/hybrid-search")
async def hybrid_search(request: SemanticSearchRequest):
    """Hybrid search combining keyword and vector similarity."""
    try:
        from src.vector_search import get_vector_search
        search = get_vector_search()

        results = search.hybrid_search(
            query=request.query,
            doc_type=request.doc_type,
            service=request.service,
            limit=request.limit
        )
        return {"results": results, "count": len(results)}
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# S3 Knowledge Base (Pattern Storage + RCA)
# =============================================================================

from src.s3_knowledge_base import get_knowledge_base, AnomalyPattern


@router.get("/api/kb/stats")
async def get_kb_stats():
    """Get knowledge base statistics."""
    kb = await get_knowledge_base()
    return kb.get_stats()


@router.get("/api/kb/patterns")
async def list_patterns(
    resource_type: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50
):
    """List patterns in the knowledge base."""
    kb = await get_knowledge_base()
    patterns = await kb.search_patterns(
        resource_type=resource_type,
        severity=severity,
        limit=limit
    )
    return {
        "patterns": [p.to_dict() for p in patterns],
        "count": len(patterns)
    }


@router.get("/api/kb/patterns/{pattern_id}")
async def get_pattern(pattern_id: str):
    """Get a specific pattern by ID."""
    kb = await get_knowledge_base()
    pattern = await kb.get_pattern(pattern_id)
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")
    return pattern.to_dict()


@router.post("/api/kb/patterns")
async def add_pattern(request: PatternAddRequest):
    """Add a new pattern to the knowledge base."""
    kb = await get_knowledge_base()
    pattern = AnomalyPattern(
        pattern_id="",
        title=request.title,
        description=request.description,
        resource_type=request.resource_type,
        severity=request.severity,
        symptoms=request.symptoms,
        root_cause=request.root_cause,
        remediation=request.remediation,
        tags=request.tags,
    )
    success = await kb.add_pattern(pattern, quality_score=request.quality_score)
    if not success:
        raise HTTPException(status_code=400, detail="Pattern rejected: quality score too low (< 0.7)")
    return {"status": "ok", "pattern_id": pattern.pattern_id}


@router.post("/api/kb/rca")
async def perform_rca(request: RCARequest):
    """Perform Root Cause Analysis using pattern matching."""
    kb = await get_knowledge_base()
    issue = {
        "id": request.id or "unknown",
        "title": request.title,
        "description": request.description,
        "resource_type": request.resource_type,
    }
    result = await kb.match_pattern(issue)
    return {
        "issue_id": result.issue_id,
        "matched_pattern": result.matched_pattern.to_dict() if result.matched_pattern else None,
        "confidence": result.confidence,
        "analysis": result.analysis,
        "recommendations": result.recommendations,
        "timestamp": result.timestamp
    }
