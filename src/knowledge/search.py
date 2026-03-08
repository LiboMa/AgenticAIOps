"""Hybrid search: vector similarity + keyword fallback + rerank.

Adapted from agenticops-chat/src/agenticops/kb/search.py.
Removed external config dependency — uses explicit parameters.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from .vector_store import SQLiteVectorStore, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class HybridResult:
    """A search result from hybrid (vector + keyword) search."""
    case_id: str
    score: float
    source: str  # "vector", "keyword", "both"
    content: str = ""
    metadata: Optional[dict] = None


def hybrid_search(
    query_text: str,
    vector_store: SQLiteVectorStore,
    query_vector: Optional[np.ndarray] = None,
    cases_dir: Optional[Path] = None,
    resource_type: str = "",
    field_name: str = "symptom",
    top_k: int = 5,
    vector_weight: float = 0.6,
    keyword_weight: float = 0.3,
    verified_boost: float = 1.2,
) -> list[HybridResult]:
    """Perform hybrid search: vector → keyword fallback → rerank.

    Args:
        query_text: Natural language query (symptoms, description).
        vector_store: SQLiteVectorStore instance.
        query_vector: Pre-computed query embedding. If None, skips vector search.
        cases_dir: Directory containing markdown case files for keyword search.
        resource_type: Resource type filter (e.g. "ec2"). Empty = all.
        field_name: Vector field to search ("symptom" or "root_cause").
        top_k: Maximum results.
        vector_weight: Weight for vector similarity score.
        keyword_weight: Weight for keyword match score.
        verified_boost: Multiplier for verified cases.

    Returns:
        Sorted list of HybridResult, best first.
    """
    # 1. Vector search
    vector_results: list[HybridResult] = []
    if query_vector is not None:
        try:
            sr = vector_store.search(
                query_vector=query_vector,
                field_name=field_name,
                resource_type=resource_type.upper() if resource_type else None,
                top_k=top_k,
            )
            vector_results = [
                HybridResult(
                    case_id=r.case_id,
                    score=r.score * vector_weight,
                    source="vector",
                    metadata=r.metadata,
                )
                for r in sr
            ]
        except Exception as e:
            logger.warning("Vector search failed: %s", e)

    # 2. Keyword fallback
    keyword_results: list[HybridResult] = []
    if cases_dir and cases_dir.is_dir():
        keyword_results = _keyword_search(
            query_text, resource_type, cases_dir, top_k, keyword_weight
        )

    # 3. Merge
    merged: dict[str, HybridResult] = {}
    for vr in vector_results:
        merged[vr.case_id] = vr
    for kr in keyword_results:
        if kr.case_id in merged:
            # Both sources matched — combine scores
            merged[kr.case_id].score += kr.score
            merged[kr.case_id].source = "both"
            if not merged[kr.case_id].content:
                merged[kr.case_id].content = kr.content
        else:
            merged[kr.case_id] = kr

    # 4. Rerank (verified boost)
    results = list(merged.values())
    for r in results:
        if r.metadata and str(r.metadata.get("verified", "false")).lower() == "true":
            r.score *= verified_boost
        r.score = min(r.score, 1.0)

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]


def _keyword_search(
    query_text: str,
    resource_type: str,
    search_dir: Path,
    top_k: int,
    weight: float,
) -> list[HybridResult]:
    """Keyword-based search over markdown case study files."""
    keywords = query_text.lower().split()
    if not keywords:
        return []

    results: list[HybridResult] = []
    for md_file in search_dir.glob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            file_text = content.lower()

            score = sum(1 for kw in keywords if kw in file_text)
            if resource_type and resource_type.lower() in file_text:
                score += 2

            if score > 0:
                norm_score = min(score / max(len(keywords) + 2, 1), 1.0) * weight
                results.append(
                    HybridResult(
                        case_id=md_file.stem,
                        score=norm_score,
                        source="keyword",
                        content=content[:500],
                    )
                )
        except Exception as e:
            logger.warning("Error reading %s: %s", md_file, e)

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]
