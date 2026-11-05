"""Private-path loopback bridge for Director Hub's single public MCP endpoint.

Reuses the independently tested existing bridge transport. Only the owner
Nginx virtual host on jipite.borealos.cn should reach this port.
"""
import os
import re
import stat
from http.server import ThreadingHTTPServer
from pathlib import Path

from bridge import build_handler


def load_token(path):
    f = Path(path)
    if not f.is_file() or f.is_symlink():
        raise RuntimeError("Hub token file missing or symlinked")
    mode = stat.S_IMODE(f.stat().st_mode)
    if mode & 0o007:
        raise RuntimeError("Hub token cannot be readable by other users")
    text = f.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise RuntimeError("Hub token must be 64 lower-case hex characters")
    return text


def main():
    token = load_token(os.getenv(
        "DIRECTOR_HUB_TOKEN_FILE", "/etc/comfyui-director-hub.token"
    ))
    srv = ThreadingHTTPServer(
        ("127.0.0.1", 8899),
        build_handler(token, upstream="http://127.0.0.1:8898/mcp")
    )
    srv.daemon_threads = True
    print("Director Hub MCP bridge ready on 127.0.0.1:8899", flush=True)
    srv.serve_forever(poll_interval=0.3)


if __name__ == "__main__":
    main()
