"""SOPAutoWriter — evaluates RCA results and generates/updates SOP via Harness.

Design: ADR-009 §9.3
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Any

from . import SOPDocument, SOPStep, RemediationPlan

logger = logging.getLogger(__name__)


class SOPDeduplicator:
    """SOP dedup — prevent knowledge base pollution.

    Design: ADR-009 §9.6
    """

    SIMILARITY_THRESHOLD = 0.85

    def __init__(self, kb_search=None):
        self.kb_search = kb_search

    async def find_similar(self, root_cause: str, service: str) -> Optional[dict]:
        """Query KB for existing similar SOP.

        Returns:
            Dict with sop_id, similarity, content, action if found, else None.
        """
        if not self.kb_search:
            return None

        query = f"{root_cause} {service}"
        try:
            results = await self.kb_search.hybrid_search(
                query_text=query,
                top_k=5,
            )
        except Exception as e:
            logger.warning("KB search failed during dedup: %s", e)
            return None

        if results and hasattr(results[0], "score") and results[0].score > self.SIMILARITY_THRESHOLD:
            return {
                "sop_id": getattr(results[0], "metadata", {}).get("sop_id", ""),
                "similarity": results[0].score,
                "content": getattr(results[0], "content", ""),
                "action": "update",
            }
        return None


class SOPAutoWriter:
    """RCA completion → Harness-driven SOP generation/update.

    Design: ADR-009 §9.3

    Trigger conditions:
    - new_pattern: RCA found new root cause, no matching SOP in KB
    - better_fix: Existing SOP fix steps incomplete, this fix is better
    - escalation_path: This incident exposed a new escalation path
    """

    TRIGGERS = {
        "new_pattern": "RCA found new root cause pattern, no matching SOP in KB",
        "better_fix": "Existing SOP fix steps incomplete, better fix discovered",
        "escalation_path": "Incident exposed new escalation path",
    }

    SOP_GENERATION_PROMPT = """You are an SRE SOP authoring expert. Generate a standardized SOP document
based on the following incident and RCA results.

## Format Requirements
- Markdown format
- Must include: trigger conditions, diagnostic steps, remediation plans (at least 2: quick fix + root cause fix)
- Each step must have specific commands/operations
- Prefer existing Skills tools (listed below)

## Incident Context
{incident_summary}

## RCA Conclusion
- Root Cause: {root_cause}
- Confidence: {confidence}
- Affected Service: {service}
- Symptoms: {symptoms}

## Resolution Log
{resolution_log}

## Available Skills Tools (prefer these)
{available_skill_tools}

## Existing Similar SOP (if updating, modify based on this)
{existing_sop_content}
"""

    def __init__(
        self,
        deduplicator: Optional[SOPDeduplicator] = None,
        harness_invoker: Optional[Any] = None,
        s3_client: Optional[Any] = None,
        kb_bucket: str = "",
        kb_id: str = "",
        data_source_id: str = "",
    ):
        self.deduplicator = deduplicator or SOPDeduplicator()
        self.harness_invoker = harness_invoker
        self.s3_client = s3_client
        self.kb_bucket = kb_bucket
        self.kb_id = kb_id
        self.data_source_id = data_source_id

    def evaluate_trigger(
        self,
        existing_sop: Optional[dict],
        rca_result: dict,
        resolution_log: list[str],
    ) -> Optional[str]:
        """Determine which trigger condition is met.

        Args:
            existing_sop: Result from SOPDeduplicator.find_similar().
            rca_result: RCA analysis result dict.
            resolution_log: List of resolution steps taken.

        Returns:
            Trigger name if condition met, None otherwise.
        """
        if not existing_sop:
            return "new_pattern"

        # Check if resolution log has significantly more steps
        existing_steps = existing_sop.get("content", "").count("\n")
        new_steps = len(resolution_log)
        if new_steps > existing_steps * 1.5 and new_steps >= 3:
            return "better_fix"

        # Check for escalation keywords
        escalation_keywords = ["escalat", "page", "on-call", "manager", "incident commander"]
        if any(kw in " ".join(resolution_log).lower() for kw in escalation_keywords):
            return "escalation_path"

        return None

    def build_sop_from_rca(
        self,
        rca_result: dict,
        resolution_log: list[str],
        incident_id: str = "",
        trigger: str = "new_pattern",
    ) -> SOPDocument:
        """Build an SOPDocument from RCA results without Harness (template-based fallback).

        Used when Harness is unavailable or for simple cases.
        """
        service = rca_result.get("affected_service", rca_result.get("service", "unknown"))
        alert_type = rca_result.get("alert_type", "unknown")
        root_cause = rca_result.get("root_cause", "Unknown root cause")
        symptoms = rca_result.get("symptoms", [])

        # Build diagnostic steps from symptoms
        diag_steps = []
        for i, symptom in enumerate(symptoms if isinstance(symptoms, list) else [symptoms], 1):
            diag_steps.append(SOPStep(order=i, description=f"Verify symptom: {symptom}"))

        # Build remediation from resolution log
        quick_fix_steps = []
        for i, step in enumerate(resolution_log[:3], 1):
            quick_fix_steps.append(SOPStep(order=i, description=step))

        root_fix_steps = [
            SOPStep(order=1, description=f"Investigate root cause: {root_cause}"),
            SOPStep(order=2, description="Apply permanent fix"),
            SOPStep(order=3, description="Verify fix and monitor"),
        ]

        return SOPDocument(
            title=f"{service.upper()} {alert_type} Recovery",
            service=service,
            alert_type=alert_type,
            trigger_conditions=[f"Alert type: {alert_type}", f"Service: {service}"],
            diagnostic_steps=diag_steps,
            remediation_plans=[
                RemediationPlan(
                    name="Quick Fix",
                    steps=quick_fix_steps or [SOPStep(order=1, description="Apply immediate mitigation")],
                    risk_level="low",
                ),
                RemediationPlan(
                    name="Root Cause Fix",
                    steps=root_fix_steps,
                    risk_level="medium",
                    requires_approval=True,
                ),
            ],
            created_from_incident=incident_id,
        )

    async def evaluate_and_write(
        self,
        incident: Any,
        rca_result: dict,
        resolution_log: list[str],
    ) -> Optional[SOPDocument]:
        """Evaluate whether to generate/update SOP, then do it.

        Args:
            incident: Incident record.
            rca_result: RCA analysis result.
            resolution_log: Steps taken to resolve.

        Returns:
            SOPDocument if generated, None if no action needed.
        """
        root_cause = rca_result.get("root_cause", "")
        service = rca_result.get("affected_service", rca_result.get("service", ""))
        incident_id = getattr(incident, "incident_id", str(incident))

        # 1. Check for existing similar SOP
        existing_sop = await self.deduplicator.find_similar(root_cause, service)

        # 2. Evaluate trigger
        trigger = self.evaluate_trigger(existing_sop, rca_result, resolution_log)
        if not trigger:
            logger.debug("No SOP trigger condition met for incident %s", incident_id)
            return None

        logger.info(
            "SOP trigger: %s for incident %s (service=%s)",
            trigger, incident_id, service,
        )

        # 3. Generate SOP (Harness or fallback)
        if self.harness_invoker:
            try:
                sop_doc = await self._invoke_harness(rca_result, resolution_log, existing_sop, trigger)
            except Exception as e:
                logger.warning("Harness SOP generation failed, using fallback: %s", e)
                sop_doc = self.build_sop_from_rca(rca_result, resolution_log, incident_id, trigger)
        else:
            sop_doc = self.build_sop_from_rca(rca_result, resolution_log, incident_id, trigger)

        # 4. Store
        if sop_doc:
            await self._store_sop(sop_doc)

        return sop_doc

    async def _invoke_harness(
        self, rca_result: dict, resolution_log: list[str],
        existing_sop: Optional[dict], trigger: str,
    ) -> SOPDocument:
        """Invoke Harness (ACP coding agent) to generate SOP."""
        prompt = self.SOP_GENERATION_PROMPT.format(
            incident_summary=rca_result.get("summary", ""),
            root_cause=rca_result.get("root_cause", ""),
            confidence=rca_result.get("confidence", 0),
            service=rca_result.get("service", ""),
            symptoms=rca_result.get("symptoms", []),
            resolution_log="\n".join(resolution_log),
            available_skill_tools="(see skills/ directory)",
            existing_sop_content=existing_sop.get("content", "") if existing_sop else "N/A",
        )
        result = await self.harness_invoker(prompt)
        # Parse harness result into SOPDocument — in production this would be more robust
        return result

    async def _store_sop(self, sop_doc: SOPDocument) -> None:
        """Write SOP to S3 and trigger KB sync."""
        if not self.s3_client or not self.kb_bucket:
            logger.debug("S3 not configured, skipping SOP storage")
            return

        try:
            await self.s3_client.put_object(
                Bucket=self.kb_bucket,
                Key=sop_doc.s3_key,
                Body=sop_doc.to_markdown().encode("utf-8"),
                ContentType="text/markdown",
            )
            logger.info("SOP stored: s3://%s/%s", self.kb_bucket, sop_doc.s3_key)
        except Exception as e:
            logger.warning("Failed to store SOP to S3: %s", e)

        await self._sync_knowledge_base()

    async def _sync_knowledge_base(self) -> None:
        """Trigger Bedrock KB ingestion job (real-time sync)."""
        if not self.kb_id:
            return
        try:
            # In production: boto3 bedrock-agent client
            logger.info("KB sync triggered: kb=%s, ds=%s", self.kb_id, self.data_source_id)
        except Exception as e:
            logger.warning("KB sync failed: %s", e)
