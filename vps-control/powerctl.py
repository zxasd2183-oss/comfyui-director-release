#!/usr/bin/env python3
"""Explicitly approved, LOCAL-TERMINAL GPU power management for Ubuntu VPS.

This tool is not an MCP endpoint. It must be launched by the VPS operator
with sudo and a TTY. It never reads a confirmation code from ChatGPT.
"""
import argparse
import fcntl
import json
import os
import sys
from pathlib import Path
from power_ops import PowerError, build_plan, read_env_file, submit_power_request

DEFAULT_CONFIG = "/etc/comfyui-director-control.env"
LOCK_PATH = "/run/lock/comfyui-director-power.lock"


def format_public(result):
    return json.dumps(result, ensure_ascii=False, indent=2)


def operate(action: str, *, apply: bool, config: dict, get_plan=build_plan,
            submit=submit_power_request, input_fn=input, output=print) -> int:
    initial = get_plan(action, config)
    output(format_public(initial))
    if not initial["allowed"]:
        output("BLOCKED: no power API request made.")
        return 3
    if not apply:
        output("PLAN ONLY: no power API request made.")
        return 0
    if not sys.stdin.isatty():
        output("BLOCKED: interactive VPS terminal required.")
        return 4
    # The operator must confirm a start can incur billing and stop can disrupt work.
    phrase = ("START GPU AND ACCEPT BILLING"
              if action == "start" else "STOP GPU - OUTPUTS VERIFIED SAVED")
    output("\nACTION CAN CHANGE GPU POWER OR BILLING.")
    output("Confirm outputs are persisted before shutdown; queue idle alone does not prove it.")
    output("Type exactly: " + phrase)
    if input_fn("Confirmation: ").strip() != phrase:
        output("Cancelled: confirmation did not match.")
        return 5
    # Re-check status *and* queue after the human review to reduce TOCTOU risk.
    second = get_plan(action, config)
    if not second["allowed"]:
        output("BLOCKED: status/queue changed since first check.")
        return 6
    result = submit(action, config)
    output(format_public(result))
    output("Provider accepted request. Query get_gpu_power_status to verify final state.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Director power API operations: VPS LOCAL ONLY")
    ap.add_argument("operation", choices=["status", "plan-start", "plan-stop",
                                           "apply-start", "apply-stop"])
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    args = ap.parse_args()
    if os.geteuid() != 0:
        ap.error("Run as root using sudo; only local operator should control power.")
    try:
        import fcntl
        with open(LOCK_PATH, "w", encoding="ascii") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            config = read_env_file(args.config)
            if args.operation == "status":
                from power_ops import get_provider_state
                print(format_public(get_provider_state(config)))
                return 0
            action = args.operation.split("-", 1)[1]
            return operate(action, apply=args.operation.startswith("apply-"),
                           config=config)
    except BlockingIOError:
        print("BLOCKED: another Director power operation is in progress.")
        return 7
    except (PowerError, OSError):
        # Never emit arbitrary network or filesystem exception messages.
        print("BLOCKED: config, provider or queue safety check failed.")
        return 8


if __name__ == "__main__":
    raise SystemExit(main())
