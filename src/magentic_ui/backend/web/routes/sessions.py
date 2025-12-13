# api/routes/sessions.py
import json
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
import httpx
from loguru import logger

from ...datamodel import Message, Run, Session, RunStatus
from ..deps import get_db
from ..config import settings

router = APIRouter()


def _langgraph_enabled() -> bool:
    return bool(settings.LANGGRAPH_API_URL)


def _langgraph_base_url() -> str:
    if not settings.LANGGRAPH_API_URL:
        raise HTTPException(status_code=500, detail="LangGraph API URL not configured")
    return settings.LANGGRAPH_API_URL.rstrip("/")


async def _langgraph_request(method: str, path: str, json_body: Dict[str, Any] | None = None) -> Dict[str, Any]:
    url = f"{_langgraph_base_url()}{path}"
    async with httpx.AsyncClient() as client:
        response = await client.request(method, url, json=json_body)

    try:
        data = response.json()
    except Exception:  # pragma: no cover - defensive against non-JSON
        data = {}

    if response.is_error:
        message = data.get("message") if isinstance(data, dict) else None
        raise HTTPException(status_code=response.status_code, detail=message or response.reason_phrase)

    return data if isinstance(data, dict) else {}


def _map_langgraph_session(raw: Dict[str, Any]) -> Dict[str, Any]:
    session_id = raw.get("session_id", raw.get("id"))
    name = raw.get("metadata", {}).get("name") or raw.get("name")
    mapped = Session(id=session_id, name=name)
    # SQLModel's model_dump will include defaults like created/updated if available
    mapped.created_at = raw.get("created_at")
    mapped.updated_at = raw.get("updated_at")
    return mapped.model_dump()


def _map_langgraph_message(raw: Dict[str, Any], session_id: int | str) -> Dict[str, Any]:
    content = raw.get("content", "")
    if not isinstance(content, str):
        content = json.dumps(content)

    message = Message(
        id=raw.get("id") or raw.get("message_id"),
        session_id=session_id,
        run_id=str(raw.get("run_id") or session_id),
        config={
            "source": raw.get("role") or raw.get("sender") or "assistant",
            "content": content,
        },
    )
    message.created_at = raw.get("created_at")
    message.updated_at = raw.get("updated_at")
    return message.model_dump()


def _map_langgraph_run(session_id: int | str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    created_at = None
    if messages:
        created_at = messages[0].get("created_at")
    created_at = created_at or datetime.utcnow().isoformat()

    task_content = messages[0].get("config", {}).get("content", "") if messages else ""

    return {
        "id": str(session_id),
        "created_at": created_at,
        "status": RunStatus.COMPLETE,
        "task": {"source": "user", "content": task_content},
        "team_result": None,
        "messages": messages,
    }


@router.get("/")
async def list_sessions(user_id: str, db=Depends(get_db)) -> Dict:
    """List all sessions for a user"""
    if _langgraph_enabled():
        data = await _langgraph_request("GET", "/sessions")
        sessions = data.get("data", {}).get("sessions") or data.get("sessions") or []
        return {"status": True, "data": [_map_langgraph_session(s) for s in sessions]}

    response = db.get(Session, filters={"user_id": user_id})
    return {"status": True, "data": response.data}


@router.get("/{session_id}")
async def get_session(session_id: int, user_id: str, db=Depends(get_db)) -> Dict:
    """Get a specific session"""
    if _langgraph_enabled():
        data = await _langgraph_request("GET", f"/sessions/{session_id}")
        session_data = data.get("data", {}).get("session") or data.get("session") or data
        return {"status": True, "data": _map_langgraph_session(session_data)}

    response = db.get(Session, filters={"id": session_id, "user_id": user_id})
    if not response.status or not response.data:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": True, "data": response.data[0]}


@router.post("/")
async def create_session(session: Session, db=Depends(get_db)) -> Dict:
    """Create a new session with an associated run"""
    if _langgraph_enabled():
        payload = {"metadata": {"name": session.name}}
        data = await _langgraph_request("POST", "/sessions", payload)
        session_id = data.get("session_id") or data.get("id") or data.get("data", {}).get("session_id")
        created = Session(id=session_id, name=session.name or data.get("metadata", {}).get("name"))
        created.created_at = data.get("created_at")
        return {"status": True, "data": created.model_dump()}

    # Create session
    session_response = db.upsert(session)
    if not session_response.status:
        raise HTTPException(status_code=400, detail=session_response.message)

    # Create associated run
    try:
        run = db.upsert(
            Run(
                session_id=session.id,
                status=RunStatus.CREATED,
                user_id=session.user_id,
                task=None,
                team_result=None,
            ),
            return_json=False,
        )
        if not run.status:
            # Clean up session if run creation failed
            raise HTTPException(status_code=400, detail=run.message)
        return {"status": True, "data": session_response.data}
    except Exception as e:
        # Clean up session if run creation failed
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put("/{session_id}")
async def update_session(
    session_id: int, user_id: str, session: Session, db=Depends(get_db)
) -> Dict:
    """Update an existing session"""
    if _langgraph_enabled():
        payload = {"metadata": {"name": session.name}}
        data = await _langgraph_request("PATCH", f"/sessions/{session_id}", payload)
        session_data = data.get("data", {}).get("session") or data.get("session") or data
        return {"status": True, "data": _map_langgraph_session(session_data), "message": "Session updated successfully"}

    # First verify the session belongs to user
    existing = db.get(Session, filters={"id": session_id, "user_id": user_id})
    if not existing.status or not existing.data:
        raise HTTPException(status_code=404, detail="Session not found")

    # Update the session
    response = db.upsert(session)
    if not response.status:
        raise HTTPException(status_code=400, detail=response.message)

    return {
        "status": True,
        "data": response.data,
        "message": "Session updated successfully",
    }


@router.delete("/{session_id}")
async def delete_session(session_id: int, user_id: str, db=Depends(get_db)) -> Dict:
    """Delete a session and all its associated runs and messages"""
    if _langgraph_enabled():
        await _langgraph_request("DELETE", f"/sessions/{session_id}")
        return {"status": True, "message": "Session deleted successfully"}

    # Delete the session
    db.delete(filters={"id": session_id, "user_id": user_id}, model_class=Session)

    return {"status": True, "message": "Session deleted successfully"}


@router.get("/{session_id}/runs")
async def list_session_runs(session_id: int, user_id: str, db=Depends(get_db)) -> Dict:
    """Get complete session history organized by runs"""

    if _langgraph_enabled():
        data = await _langgraph_request("GET", f"/sessions/{session_id}/messages")
        raw_messages = data.get("messages") or data.get("data", {}).get("messages") or []
        messages = [_map_langgraph_message(m, session_id) for m in raw_messages]
        run = _map_langgraph_run(session_id, messages)
        return {"status": True, "data": {"runs": [run]}}

    try:
        # 1. Verify session exists and belongs to user
        session = db.get(
            Session, filters={"id": session_id, "user_id": user_id}, return_json=False
        )
        if not session.status:
            raise HTTPException(
                status_code=500, detail="Database error while fetching session"
            )
        if not session.data:
            raise HTTPException(
                status_code=404, detail="Session not found or access denied"
            )

        # 2. Get ordered runs for session
        runs = db.get(
            Run, filters={"session_id": session_id}, order="asc", return_json=False
        )
        if not runs.status:
            raise HTTPException(
                status_code=500, detail="Database error while fetching runs"
            )

        # 3. Build response with messages per run
        run_data = []
        if runs.data:  # It's ok to have no runs
            for run in runs.data:
                try:
                    # Get messages for this specific run
                    messages = db.get(
                        Message,
                        filters={"run_id": run.id},
                        order="asc",
                        return_json=False,
                    )
                    if not messages.status:
                        logger.error(f"Failed to fetch messages for run {run.id}")
                        # Continue processing other runs even if one fails
                        messages.data = []

                    run_data.append(
                        {
                            "id": str(run.id),
                            "created_at": run.created_at,
                            "status": run.status,
                            "task": run.task,
                            "team_result": run.team_result,
                            "messages": messages.data or [],
                            "input_request": getattr(run, "input_request", None),
                        }
                    )
                except Exception as e:
                    logger.error(f"Error processing run {run.id}: {str(e)}")
                    # Include run with error state instead of failing entirely
                    run_data.append(
                        {
                            "id": str(run.id),
                            "created_at": run.created_at,
                            "status": "ERROR",
                            "task": run.task,
                            "team_result": None,
                            "messages": [],
                            "error": f"Failed to process run: {str(e)}",
                            "input_request": getattr(run, "input_request", None),
                        }
                    )

        return {"status": True, "data": {"runs": run_data}}

    except HTTPException:
        raise  # Re-raise HTTP exceptions
    except Exception as e:
        logger.error(f"Unexpected error in list_messages: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Internal server error while fetching session data"
        ) from e
