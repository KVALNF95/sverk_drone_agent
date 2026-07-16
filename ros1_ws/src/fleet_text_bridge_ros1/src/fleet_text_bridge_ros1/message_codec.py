from __future__ import annotations

import json
from typing import Any, Dict, Optional, Union


def decode_json_object(payload: Union[str, bytes]) -> Dict[str, Any]:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def validate_command(data: Dict[str, Any], expected_robot_id: str) -> None:
    for key in ("message_id", "robot_id", "text"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError("Missing or invalid %s" % key)
    if data["robot_id"] != expected_robot_id:
        raise ValueError("robot_id does not match bridge configuration")


def _best_text(data: Dict[str, Any], raw_payload: str) -> str:
    for key in ("text", "message", "reply", "answer"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    event = data.get("event")
    if isinstance(event, str) and event.strip():
        return event.strip()
    if data:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return raw_payload.strip()


def normalize_agent_payload(
    payload: str,
    *,
    expected_robot_id: str,
    active_message_id: Optional[str],
    answer: bool,
) -> Dict[str, str]:
    """Normalize protocol envelopes and legacy plain-text ROS output.

    The bridge serializes commands, so an old agent response without message_id
    can be safely associated with the one active server command.
    """
    raw = str(payload or "").strip()
    if not raw:
        raise ValueError("ROS payload is empty")

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None

    data = parsed if isinstance(parsed, dict) else {"text": raw}
    supplied_robot_id = data.get("robot_id")
    if supplied_robot_id not in (None, "", expected_robot_id):
        raise ValueError("robot_id does not match bridge configuration")

    message_id = data.get("message_id")
    if not isinstance(message_id, str) or not message_id.strip():
        message_id = active_message_id
    if not isinstance(message_id, str) or not message_id.strip():
        raise ValueError("Cannot correlate ROS payload: no active message_id")

    text = _best_text(data, raw)
    if answer:
        status = data.get("status")
        if status not in ("completed", "error"):
            event = str(data.get("event") or "").lower()
            lowered = text.lower()
            status = "error" if event in {"error", "busy", "failed"} or lowered.startswith("ошибка") else "completed"
    else:
        status = data.get("status")
        if not isinstance(status, str) or not status.strip():
            event = str(data.get("event") or "").lower()
            status = "error" if event in {"error", "busy", "failed"} else "running"

    return {
        "message_id": message_id.strip(),
        "robot_id": expected_robot_id,
        "status": str(status),
        "text": text,
    }


def validate_outgoing(data: Dict[str, Any], expected_robot_id: str, *, answer: bool) -> None:
    if data.get("robot_id") != expected_robot_id:
        raise ValueError("robot_id does not match bridge configuration")
    for key in ("message_id", "robot_id", "status", "text"):
        if not isinstance(data.get(key), str):
            raise ValueError("Missing or invalid %s" % key)
    if answer and data["status"] not in {"completed", "error"}:
        raise ValueError("Answer status must be completed or error")
