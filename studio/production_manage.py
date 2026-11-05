#!/usr/bin/env python3
"""V0.9 offline production management. All writes require a trusted local shell.

No public write endpoints, no Microsoft identity assumption, no GPU requests.
Actor is a LOCAL operator label, not an authenticated web identity.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from contextlib import closing

from production_core import (
    ProductionError, open_db, create_project, create_episode, create_shot,
    add_asset, attach_asset, create_finding, draft_exception, decide_exception,
    dashboard, verify_chain,
)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Director Studio V0.9 production ledger")
    ap.add_argument("--db", default=os.environ.get(
        "DIRECTOR_PRODUCTION_DB", "/var/lib/director-studio/production.sqlite"))
    ap.add_argument("--actor", default="local_operator",
                    help="Local audit label only; not a verified Microsoft identity")
    sp = ap.add_subparsers(dest="command", required=True)
    p = sp.add_parser("create-project")
    p.add_argument("--id", required=True); p.add_argument("--title", required=True)
    p = sp.add_parser("create-episode")
    p.add_argument("--project", required=True); p.add_argument("--id", required=True)
    p.add_argument("--title", required=True); p.add_argument("--ordinal", type=int, required=True)
    p = sp.add_parser("create-shot")
    p.add_argument("--project", required=True); p.add_argument("--episode", required=True)
    p.add_argument("--id", required=True); p.add_argument("--ordinal", type=int, required=True)
    p.add_argument("--duration-ms", type=int, required=True)
    p = sp.add_parser("register-asset")
    p.add_argument("--project", required=True); p.add_argument("--id", required=True)
    p.add_argument("--kind", required=True)
    p.add_argument("--subject", required=True); p.add_argument("--version", type=int, required=True)
    p.add_argument("--sha256", required=True); p.add_argument("--rights-ref", default="")
    p = sp.add_parser("attach-asset")
    p.add_argument("--project", required=True); p.add_argument("--episode", required=True)
    p.add_argument("--shot", required=True); p.add_argument("--asset", required=True)
    p.add_argument("--purpose", required=True)
    p = sp.add_parser("report-finding")
    p.add_argument("--project", required=True); p.add_argument("--episode", required=True)
    p.add_argument("--shot", required=True); p.add_argument("--id", required=True)
    p.add_argument("--attribute", required=True); p.add_argument("--evidence-sha256", required=True)
    p.add_argument("--detail", required=True)
    p = sp.add_parser("draft-exception")
    p.add_argument("--id", required=True); p.add_argument("--finding", required=True)
    p.add_argument("--start-ms", type=int, required=True); p.add_argument("--end-ms", type=int, required=True)
    p.add_argument("--change", required=True); p.add_argument("--rationale", required=True)
    p.add_argument("--evidence-sha256", required=True); p.add_argument("--bound-asset")
    p = sp.add_parser("decide-exception")
    p.add_argument("--id", required=True); p.add_argument("--decision", choices=("approve","revoke"),
                   required=True)
    p.add_argument("--expected-revision", type=int, required=True)
    p.add_argument("--i-reviewed-evidence", action="store_true",
                   help="Required explicit operator confirmation")
    sp.add_parser("dashboard")
    sp.add_parser("verify-audit")
    args = ap.parse_args(argv)

    try:
        with closing(open_db(args.db)) as db:
            if args.command == "create-project":
                create_project(db, args.id,args.title,actor=args.actor)
                result={"ok":True,"project_id":args.id}
            elif args.command == "create-episode":
                create_episode(db,args.project,args.id,args.title,args.ordinal,actor=args.actor)
                result={"ok":True,"episode_id":args.id}
            elif args.command == "create-shot":
                create_shot(db,args.project,args.episode,args.id,args.ordinal,
                            args.duration_ms,actor=args.actor)
                result={"ok":True,"shot_id":args.id}
            elif args.command == "register-asset":
                add_asset(db,args.id,args.project,args.kind,args.subject,args.version,
                          args.sha256,args.rights_ref,actor=args.actor)
                result={"ok":True,"asset_id":args.id}
            elif args.command == "attach-asset":
                attach_asset(db,args.project,args.episode,args.shot,args.asset,args.purpose,
                             actor=args.actor)
                result={"ok":True,"linked_asset":args.asset}
            elif args.command == "report-finding":
                create_finding(db,args.id,args.project,args.episode,args.shot,args.attribute,
                               args.evidence_sha256,args.detail,actor=args.actor)
                result={"ok":True,"finding_id":args.id}
            elif args.command == "draft-exception":
                draft_exception(db,args.id,args.finding,args.start_ms,args.end_ms,
                                args.change,args.rationale,args.evidence_sha256,
                                args.bound_asset,actor=args.actor)
                result={"ok":True,"exception_id":args.id,"status":"draft"}
            elif args.command == "decide-exception":
                result = decide_exception(db,args.id,args.decision,args.expected_revision,
                          actor=args.actor,
                          confirmation="I_HAVE_REVIEWED_EVIDENCE" if args.i_reviewed_evidence else "")
                result["ok"]=True
            elif args.command == "verify-audit":
                result={"ok":verify_chain(db)}
                print(json.dumps(result,ensure_ascii=False))
                return 0 if result["ok"] else 3
            else:
                result=dashboard(db)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
        return 0
    except (ProductionError,sqlite3.Error,ValueError,OSError) as exc:
        print("Studio production operation refused: "+str(exc), file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
