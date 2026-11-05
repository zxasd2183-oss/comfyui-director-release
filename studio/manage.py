#!/usr/bin/env python3
"""Director Studio operator CLI. No cloud/GPU commands."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from studio_core import StudioError, connect, dispatch_eligible, import_plan, snapshot

STAGES = {
    "pending": "planned", "submitting": "rendering",
    "queued": "queued", "done": "rendered",
    "rejected": "failed", "failed": "failed", "uncertain": "unknown",
}


def sync_runner(db, path):
    """Read a copied V0.7 SQLite status DB, never its prompts or prompt IDs."""
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise StudioError("invalid_runner_database")
    input_db = sqlite3.connect("file:" + source.as_posix() + "?mode=ro", uri=True)
    try:
        states = input_db.execute("SELECT shot_id,state FROM runs").fetchall()
    except sqlite3.Error:
        raise StudioError("invalid_runner_schema") from None
    finally:
        input_db.close()
    if len(states) > 500:
        raise StudioError("runner_state_too_large")
    changed = 0
    db.execute("BEGIN IMMEDIATE")
    try:
        for sid, state in states:
            if not isinstance(sid, str) or state not in STAGES:
                raise StudioError("invalid_runner_state")
            row = db.execute("SELECT stage FROM shots WHERE id=?", (sid,)).fetchone()
            if row is None:
                raise StudioError("runner_shot_not_in_plan")
            stage = STAGES[state]
            if stage != row["stage"]:
                db.execute("UPDATE shots SET stage=?,revision=revision+1 WHERE id=?",
                           (stage, sid))
                changed += 1
        if changed:
            db.execute(
                "INSERT INTO studio_events(at,actor,action,target,detail) VALUES "
                "(strftime('%s','now'),'runner_import','runner_state_sync',NULL,?)",
                ("changed_shots:" + str(changed),))
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    return {"ok": True, "changed": changed, "real_time_sync": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Director Studio V0.8 operator import/status")
    parser.add_argument("--db", default=os.getenv(
        "DIRECTOR_STUDIO_DB", "/var/lib/director-studio/studio.sqlite"))
    commands = parser.add_subparsers(dest="command", required=True)
    imp = commands.add_parser("import-plan", help="Import redacted shot structure")
    imp.add_argument("--plan", required=True)
    synch = commands.add_parser("sync-runner", help="Sync a locally copied runner DB snapshot")
    synch.add_argument("--runner-db", required=True)
    commands.add_parser("status")
    commands.add_parser("dispatch-eligible")
    args = parser.parse_args(argv)
    try:
        with closing(connect(args.db)) as db:
            if args.command == "import-plan":
                result = import_plan(db, args.plan)
            elif args.command == "sync-runner":
                result = sync_runner(db, args.runner_db)
            elif args.command == "dispatch-eligible":
                result = {"eligible": dispatch_eligible(db),
                          "note": "advisory_only_not_connected_to_gpu_dispatcher"}
            else:
                s = snapshot(db)
                result = {
                    "shots": len(s["shots"]), "dispatch_paused": s["dispatch_paused"],
                    "held": sum(x["held"] for x in s["shots"]),
                    "mode": s["mode"],
                }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (StudioError, OSError, sqlite3.Error, ValueError):
        print("Director Studio command refused; check plan/permissions safely.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
