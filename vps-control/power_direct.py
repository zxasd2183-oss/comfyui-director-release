"""One-call GPU power control behind the existing owner-authenticated Director Hub.

The public Hub bridge already authenticates a high-entropy private MCP path.
This module does NOT expose an anonymous endpoint or bypass that authentication.
No TOTP/phone/browser approval is required for each operation. A database lease,
short cooldown, auditable state, current provider preflight and a second preflight
before submitting protect against duplicated/unsafe provider requests.
"""
from __future__ import annotations

import secrets
import time

from power_ops import build_plan, submit_power_request
from power_v03 import DB_DEFAULT, _audit, connect

COOLDOWN_SECONDS = 90
LEASE_SECONDS = 300


def execute_direct(action: str, config: dict, db_path: str = DB_DEFAULT, *,
                   plan_fn=build_plan, submit_fn=submit_power_request,
                   now: float | None = None) -> dict:
    """Submit ONE provider operation, not an approval request.

    Provider acceptance is NOT proof of a fully booted/stopped machine. Network
    uncertainty is never retried automatically; inspect get_gpu_power_status.
    """
    if action not in ("start", "stop"):
        return {"ok": False, "reason": "invalid_action"}
    current = time.time() if now is None else now
    try:
        plan = plan_fn(action, config)
    except Exception:
        return {"ok": False, "reason": "preflight_unavailable"}
    if plan.get("allowed") is not True:
        return {"ok": False, "reason": plan.get("reason", "preflight_blocked")}
    request_id = secrets.token_urlsafe(24)
    with connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        active = db.execute(
            "SELECT COUNT(*) FROM requests WHERE state='executing' OR "
            "(state='pending' AND expires>?)", (current,)).fetchone()[0]
        recent = db.execute(
            "SELECT COUNT(*) FROM audit WHERE event='direct_initiated' AND at>?",
            (current - COOLDOWN_SECONDS,)).fetchone()[0]
        if active or recent:
            db.execute("ROLLBACK")
            return {"ok": False, "reason": "power_operation_in_progress_or_cooldown"}
        db.execute(
            "INSERT INTO requests(id,action,state,created,expires,updated) "
            "VALUES(?,?,?,?,?,?)",
            (request_id, action, "executing", current, current + LEASE_SECONDS, current))
        _audit(db, request_id, action, "direct_initiated", current)
        db.execute("COMMIT")

    state, result = "blocked", "state_or_ue_workload_changed"
    try:
        # A STOP still needs a verified idle Windows UE Worker at this instant.
        # This prevents turning off an actively rendering instance.
        updated = plan_fn(action, config)
        if updated.get("allowed") is True:
            response = submit_fn(action, config)
            if response.get("accepted") is True:
                state, result = "submitted", "accepted_by_provider_verify_final_state"
            else:
                state, result = "error", "provider_not_accepted"
    except Exception:
        state, result = "error", "provider_request_uncertain_check_status"
    with connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "UPDATE requests SET state=?,result=?,updated=? "
            "WHERE id=? AND state='executing'",
            (state, result, time.time(), request_id))
        _audit(db, request_id, action, state, time.time())
        db.execute("COMMIT")
    return {
        "ok": state == "submitted", "request_id": request_id, "action": action,
        "state": state, "result": result, "approval_required": False,
        "final_state_verified": False,
    }
