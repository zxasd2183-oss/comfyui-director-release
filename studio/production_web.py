"""Authenticated, narrowly scoped Director Studio web project authoring.

Only a verified Microsoft Studio owner session may reach this dispatcher.
No GPU, ComfyUI, asset uploads, exception approvals or power operations.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import closing

from production_core import (
    ProductionError, _ident, create_project, create_episode, open_db, verify_chain,
)

ALLOWED_ACTIONS = frozenset({"create_project", "create_episode"})
FIELDS = {
    "create_project": frozenset({"action", "csrf", "project_id", "title"}),
    "create_episode": frozenset(
        {"action", "csrf", "project_id", "episode_id", "title", "ordinal"}),
}


class ProductionWebError(ValueError):
    def __init__(self, reason, status=400):
        self.reason = reason
        self.status = status
        super().__init__(reason)


def operator_from_verified_session(session):
    """Audit label derives from an authenticated server-side sub, not request JSON."""
    if not isinstance(session, dict):
        raise ProductionWebError("microsoft_owner_required", 403)
    subject = session.get("sub")
    if not isinstance(subject, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,256}", subject):
        raise ProductionWebError("microsoft_owner_required", 403)
    return "owner_" + hashlib.sha256(subject.encode("utf-8")).hexdigest()[:24]


def create_from_web(db_path, data, session):
    actor = operator_from_verified_session(session)
    if not isinstance(data, dict):
        raise ProductionWebError("invalid_production_action")
    action = data.get("action")
    if action not in ALLOWED_ACTIONS:
        raise ProductionWebError("unsupported_production_action", 403)
    if set(data) != FIELDS[action]:
        raise ProductionWebError("invalid_production_fields")
    try:
        # Reject writes if existing audit history is corrupt. A local sysadmin
        # can restore a trusted backup and verify it before resuming edits.
        with closing(open_db(db_path, initialize=True)) as db:
            if not verify_chain(db):
                raise ProductionWebError("audit_integrity_failure", 409)
            if action == "create_project":
                _ident(data["project_id"])
                if db.execute("SELECT COUNT(*) FROM projects").fetchone()[0] >= 100:
                    raise ProductionWebError("project_limit_reached", 409)
                create_project(db, data["project_id"], data["title"], actor=actor)
                return {"ok": True, "action":action,
                        "project_id":data["project_id"],
                        "gpu_action":False}
            # The project must exist; do not allow UI to create implicit work.
            _ident(data["project_id"])
            if db.execute("SELECT COUNT(*) FROM episodes WHERE project_id=?",
                          (data["project_id"],)).fetchone()[0] >= 1000:
                raise ProductionWebError("episode_limit_reached", 409)
            create_episode(db, data["project_id"],data["episode_id"],
                           data["title"],data["ordinal"],actor=actor)
            return {"ok":True,"action":action,
                    "project_id":data["project_id"],
                    "episode_id":data["episode_id"],
                    "gpu_action":False}
    except ProductionError as exc:
        raise ProductionWebError(str(exc)) from None
    except sqlite3.IntegrityError:
        # Duplicate identifier, duplicate episode ordinal, unknown project etc.
        raise ProductionWebError("already_exists_or_invalid_parent", 409) from None
    except sqlite3.Error:
        raise ProductionWebError("production_storage_unavailable",503) from None
