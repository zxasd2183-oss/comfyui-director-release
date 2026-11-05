#!/usr/bin/env bash
# V0.8.1: upgrade local Studio assets, then install protected public /studio/.
# Leaves Jipite MCP, mobile approvals, OIDC, feeds, GPU power unchanged.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo "ERROR: run with sudo on owner VPS" >&2; exit 2; }
SRC="$(cd "$(dirname "$0")" && pwd)"
[[ -f "$SRC/configure_studio_nginx.py" ]] || exit 2
systemctl is-active --quiet director-studio || {
  echo "ERROR: Install the private V0.8 Studio service first" >&2
  exit 2
}
systemctl is-active --quiet nginx || {
  echo "ERROR: Existing Nginx must be healthy" >&2
  exit 2
}
# The V0.8 installer uses root-owned files, reloads only director-studio,
# and runs all offline Studio tests. This keeps the original SSH-only access.
bash "$SRC/install-v08.sh"
python3 "$SRC/configure_studio_nginx.py"
# No authentication credentials are used in this check. A 401 is expected.
echo "Director Studio public route requires HTTPS Basic Auth."
echo "Browser URL: https://jipite.borealos.cn/studio/"
echo "The original SSH-only http://127.0.0.1:8900 access remains enabled."
echo "Verify public unauthenticated URL returns 401; do NOT disable auth_basic."
