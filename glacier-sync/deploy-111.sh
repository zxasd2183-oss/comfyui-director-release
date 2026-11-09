#!/usr/bin/env bash
# Deployment entrypoint for the 111.230.226.74 VPS.
# Requires the sync-only 8443 server block in zz-new-domains.conf.
set -Eeuo pipefail
[ "${EUID}" -eq 0 ] || { echo "Run: sudo bash glacier-sync/deploy-111.sh" >&2; exit 1; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$HERE/install-vps.sh"
bash "$HERE/activate-vhost.sh"
echo "Glacier Sync: backend and HTTPS reverse proxy deployed."
echo "Registration invite remains private at /etc/glacier-sync/secrets.env."
