"""Router: /api/issues - Issue management."""

from typing import Optional

from fastapi import APIRouter, HTTPException

from routers.schemas import IssueCreateRequest, IssueUpdateRequest
from routers.deps import get_issue_manager, get_runbook_executor, logger

router = APIRouter(tags=["issues"])


@router.get("/api/issues")
async def list_issues(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    namespace: Optional[str] = None,
    limit: int = 50
):
    """List issues with optional filters."""
    manager = get_issue_manager()
    if not manager:
        return {"error": "Issue Manager not available", "issues": []}

    try:
        issues = manager.list_issues(
            status=status,
            severity=severity,
            namespace=namespace,
            limit=limit
        )
        return {"issues": [i.to_dict() for i in issues]}
    except Exception as e:
        return {"error": str(e), "issues": []}


@router.get("/api/issues/dashboard")
async def get_issues_dashboard():
    """Get dashboard summary data."""
    manager = get_issue_manager()
    if not manager:
        return {"error": "Issue Manager not available"}

    try:
        data = manager.get_dashboard_data()
        return data
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/issues/{issue_id}")
async def get_issue(issue_id: str):
    """Get issue by ID."""
    manager = get_issue_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Issue Manager not available")

    issue = manager.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    return issue.to_dict()


@router.post("/api/issues")
async def create_issue(request: IssueCreateRequest):
    """Create a new issue."""
    manager = get_issue_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Issue Manager not available")

    try:
        from src.issues import IssueType

        type_map = {
            "oom_killed": IssueType.OOM_KILLED,
            "cpu_throttling": IssueType.CPU_THROTTLING,
            "crash_loop": IssueType.CRASH_LOOP,
            "image_pull_error": IssueType.IMAGE_PULL_ERROR,
            "memory_pressure": IssueType.MEMORY_PRESSURE,
        }
        issue_type = type_map.get(request.pattern_id, IssueType.UNKNOWN)

        issue = manager.create_issue(
            issue_type=issue_type,
            title=request.title,
            namespace=request.namespace,
            resource=request.resource_name,
            description=request.description or "",
            symptoms=[request.root_cause] if request.root_cause else [],
            metadata={
                "resource_type": request.resource_type,
                "root_cause": request.root_cause,
                "remediation": request.remediation,
                "auto_fixable": request.auto_fixable,
                "pattern_id": request.pattern_id
            }
        )
        return issue.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/api/issues/{issue_id}")
async def update_issue(issue_id: str, request: IssueUpdateRequest):
    """Update issue fields."""
    manager = get_issue_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Issue Manager not available")

    try:
        from src.issues import IssueStatus, Severity

        status = IssueStatus(request.status) if request.status else None
        severity = Severity(request.severity) if request.severity else None

        issue = manager.update_issue(
            issue_id=issue_id,
            status=status,
            severity=severity,
            root_cause=request.root_cause,
            remediation=request.remediation
        )

        if not issue:
            raise HTTPException(status_code=404, detail="Issue not found")

        return issue.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/issues/{issue_id}/fix")
async def fix_issue(issue_id: str):
    """Trigger auto-fix for an issue."""
    manager = get_issue_manager()
    executor = get_runbook_executor()

    if not manager:
        raise HTTPException(status_code=503, detail="Issue Manager not available")

    issue = manager.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    if not issue.auto_fixable:
        raise HTTPException(status_code=400, detail="Issue is not auto-fixable")

    if executor:
        try:
            pattern_id = issue.metadata.get("pattern_id") or (issue.type.value if hasattr(issue.type, 'value') else str(issue.type))

            context = {
                "namespace": issue.namespace,
                "resource_type": issue.metadata.get("resource_type", "Pod"),
                "resource_name": issue.resource,
                "container_name": issue.metadata.get("container_name", "main"),
            }

            execution = executor.execute_for_pattern(pattern_id, context, issue_id=issue_id)

            if not execution and hasattr(issue.type, 'value'):
                execution = executor.execute_for_pattern(issue.type.value, context, issue_id=issue_id)

            if execution:
                manager.record_fix_attempt(
                    issue_id=issue_id,
                    action=execution.runbook_id,
                    result=f"Execution {execution.execution_id}: {execution.status.value}",
                    success=execution.status.value == "success",
                )

                return {
                    "status": "initiated",
                    "execution_id": execution.execution_id,
                    "runbook_id": execution.runbook_id,
                    "runbook_name": execution.runbook_id.replace("-", " ").title(),
                    "steps_total": len(execution.step_results),
                    "result": execution.status.value,
                }
            else:
                try:
                    from src.sop_system import get_sop_executor, get_sop_store
                    sop_store = get_sop_store()
                    keyword = issue.type.value.replace("_", " ") if hasattr(issue.type, 'value') else str(issue.type)
                    matching_sops = sop_store.search_sops(keyword)
                    if matching_sops:
                        sop = matching_sops[0]
                        sop_executor = get_sop_executor()
                        sop_exec = sop_executor.start_execution(
                            sop_id=sop.sop_id,
                            triggered_by="auto_fix",
                            context={"issue_id": issue_id, **context},
                        )
                        if sop_exec:
                            return {
                                "status": "initiated",
                                "execution_id": sop_exec.execution_id,
                                "runbook_id": sop.sop_id,
                                "runbook_name": sop.name,
                                "fix_type": "sop",
                            }
                except Exception as sop_err:
                    logger.debug(f"SOP fallback failed: {sop_err}")

                return {"status": "no_runbook", "message": f"No runbook found for pattern: {pattern_id}"}

        except Exception as e:
            return {"status": "error", "message": str(e)}

    return {"status": "no_executor", "message": "Runbook executor not available"}
