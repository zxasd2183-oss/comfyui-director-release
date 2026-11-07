#!/usr/bin/env python3
"""Local service-identity only picture-cut preflight and explicit assembly.

No network, no GPU power or prompts. For final sound master, use separate
approved audio/rights workflow after viewing this immutable silent/guide cut.
"""
import argparse
import json
import os
from pathlib import Path
import sys

from picture_cuts import get_readiness, assemble, PictureCutError


def main(argv=None):
    parser=argparse.ArgumentParser(description="Director local approved picture cut")
    parser.add_argument("--db",default=os.environ.get(
        "DIRECTOR_PRODUCTION_DB","/var/lib/director-studio/production.sqlite"))
    parser.add_argument("--project",required=True)
    parser.add_argument("--episode",required=True)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check",action="store_true")
    group.add_argument("--assemble",action="store_true")
    parser.add_argument("--expected-manifest-sha",
        help="Exact 64-byte SHA-256 from a previous approved preflight")
    parser.add_argument("--acknowledge-local-cpu",action="store_true")
    args=parser.parse_args(argv)
    ready=get_readiness(args.db,args.project,args.episode)
    if args.check:
        print(json.dumps({"ok":True,"project_id":ready["project_id"],
            "episode_id":ready["episode_id"],
            "shot_count":ready["shot_count"],
            "approved_count":ready["approved_count"],
            "ready":ready["ready"],"blocked":ready["blocked"],
            "source_manifest_sha256":ready["source_manifest_sha256"],
            "gpu_action":False},ensure_ascii=False,indent=2))
        return 0
    if not args.acknowledge_local_cpu:
        raise PictureCutError("explicit_local_cpu_assembly_acknowledgment_required")
    if (not isinstance(args.expected_manifest_sha,str) or
        len(args.expected_manifest_sha)!=64 or
        args.expected_manifest_sha!=ready["source_manifest_sha256"]):
        raise PictureCutError("approved_manifest_checksum_mismatch",409)
    if not ready["ready"]:
        raise PictureCutError("approved_picture_cut_incomplete",409)
    result=assemble(args.db,args.project,args.episode,
                    "local_studio_picture_cut_operator")
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0


if __name__=="__main__":
    try:sys.exit(main())
    except (PictureCutError,OSError,ValueError) as exc:
        print("Local picture-cut error: "+str(exc),file=sys.stderr)
        sys.exit(2)
