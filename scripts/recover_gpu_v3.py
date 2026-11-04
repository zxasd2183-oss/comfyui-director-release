#!/usr/bin/env python3
"""Recover an installed GPU Director V3 after a powered-off GPU boots.

Only checks health, starts an ALREADY INSTALLED local supervisor if missing,
and optionally starts a temporary read-only HTTPS Quick Tunnel. It NEVER
starts/stops a GPU instance, executes ComfyUI jobs, installs packages, or
reads/discloses provider credentials.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.request import Request, urlopen

MIN_TOOLS = {"get_studio_status", "get_queue_summary",
             "get_upgrade_readiness", "audit_h3_workflow"}

def json_get(url: str, *, data: dict | None = None, timeout: float = 4):
    headers = {"Accept": "application/json"}
    payload = None
    if data is not None:
        payload = json.dumps(data, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=payload, headers=headers,
                  method="POST" if payload is not None else "GET")
    with urlopen(req, timeout=timeout) as response:
        raw = response.read(131073)
    if len(raw) > 131072:
        raise ValueError("Oversize response")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Unexpected response")
    return value


def read_installed(root: Path) -> tuple[int, str]:
    config_file = root / "config.json"
    if config_file.is_symlink():
        raise ValueError("Config symlinks not supported")
    obj = json.loads(config_file.read_text(encoding="utf-8"))
    port, private_path = obj.get("port"), obj.get("mcp_path")
    if not isinstance(port, int) or isinstance(port, bool) or port != 8790:
        raise ValueError("Expected current GPU Director V3 port 8790; never touch Slink 8765")
    if (not isinstance(private_path, str) or
            not re.fullmatch(r"/mcp/[0-9a-fA-F]{48,128}", private_path)):
        raise ValueError("Invalid private MCP path")
    return port, private_path


def director_health(port: int) -> bool:
    try:
        result = json_get(f"http://127.0.0.1:{port}/health")
        return result.get("ok") is True and result.get("version") == "0.3.0"
    except Exception:
        return False


def comfyui_health(port: int = 8188) -> bool:
    try:
        data = json_get(f"http://127.0.0.1:{port}/system_stats")
        return "system" in data or "devices" in data
    except Exception:
        return False


def start_installed_director(root: Path, port: int, timeout: int = 30) -> bool:
    if director_health(port):
        return True
    script = root / "controller" / "start.sh"
    if not script.is_file() or script.is_symlink():
        return False
    try:
        result = subprocess.run(["bash", str(script)], cwd=script.parent,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=20, check=False)
        if result.returncode != 0:
            return False
        for _ in range(timeout):
            if director_health(port):
                return True
            time.sleep(1)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return False


def tools_ready(port: int, path: str) -> tuple[bool, int]:
    try:
        response = json_get(f"http://127.0.0.1:{port}{path}", data={
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        tools = response.get("result", {}).get("tools", [])
        names = {item.get("name") for item in tools if isinstance(item, dict)}
        return MIN_TOOLS.issubset(names) and len(names) >= 8, len(names)
    except Exception:
        return False, 0


def start_quick_tunnel(root: Path, port: int, private_path: str,
                       max_wait: int = 40) -> tuple[str, int]:
    binary = shutil.which("cloudflared")
    if not binary:
        raise RuntimeError("cloudflared is not installed")
    # Never place the private URL token on the cloudflared command line.
    log = root / "v3-recovery-tunnel.log"
    fd = os.open(str(log), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        process = subprocess.Popen([binary, "tunnel", "--url",
                                    f"http://127.0.0.1:{port}"],
                                   cwd=str(root), stdout=handle,
                                   stderr=subprocess.STDOUT, start_new_session=True)
    pid_file = root / "v3-recovery-tunnel.pid"
    pid_file.write_text(str(process.pid), encoding="ascii")
    pid_file.chmod(0o600)
    public = None
    for _ in range(max_wait):
        if process.poll() is not None:
            break
        content = log.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", content)
        if match:
            public = match.group(0)
            try:
                live = json_get(public + "/health", timeout=5)
                if live.get("version") == "0.3.0":
                    return public + private_path, process.pid
            except Exception:
                pass
        time.sleep(1)
    raise RuntimeError("Temporary HTTPS tunnel not ready (inspect private log on GPU)")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Restore GPU Director V3 without starting GPU or generating tasks")
    parser.add_argument("--root", default=str(Path.home() / ".comfyui-director"))
    parser.add_argument("--tunnel", action="store_true",
                        help="Start new Cloudflare Quick Tunnel and print private URL locally")
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser()
    try:
        port, private_path = read_installed(root)
    except (OSError, ValueError, json.JSONDecodeError):
        print("ERROR: V3 installation/configuration missing or invalid. Nothing changed.")
        return 2

    print("Director V3 after boot: GPU power controls are NOT invoked.")
    if director_health(port):
        print("Supervisor: already healthy on localhost 8790")
    else:
        print("Supervisor: offline; starting previously installed controller/start.sh")
        if not start_installed_director(root, port):
            print("ERROR: Supervisor did not become healthy. Check start.sh on GPU locally.")
            return 3
    print("Supervisor: healthy")
    ok, count = tools_ready(port, private_path)
    if not ok:
        print(f"ERROR: Director MCP tool check failed (found {count} tools).")
        return 4
    print(f"Director V3 MCP: {count} tools ready")
    if comfyui_health():
        print("ComfyUI localhost 8188: responding")
    else:
        print("WARNING: ComfyUI localhost 8188 is not responding.")
        print("Do NOT start a second ComfyUI blindly. Check provider auto-start/ComfyUI logs.")
    if not args.tunnel:
        print("Local checks complete. To reconnect ChatGPT, use --tunnel.")
        return 0
    try:
        url, pid = start_quick_tunnel(root, port, private_path)
    except RuntimeError:
        print("ERROR: HTTPS tunnel failed. Check cloudflared locally; no GPU power actions were taken.")
        return 5
    print("\n=== PRIVATE URL. ENTER ONLY IN ChatGPT PLUGIN SETTINGS ===")
    print(url)
    print("=== NEVER SEND THIS FULL URL OR PRIVATE PATH IN CHAT ===")
    print(f"Cloudflared process PID: {pid}")
    print("This Quick Tunnel is temporary and will change after GPU power-off.")
    print("VPS safety preflight also needs the NEW URL in DIRECTOR_GPU_MCP_URL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
