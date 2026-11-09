#!/usr/bin/env bash
# Install Glacier Sync in its own Unix user and localhost-only service.
# Does not touch existing Director / Jipite services or configure DNS/TLS.
set -Eeuo pipefail
if [ "${EUID}" -ne 0 ]; then
  echo "Run as root on the Glacier VPS: sudo bash glacier-sync/install-vps.sh" >&2
  exit 1
fi
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for required in server.py requirements.txt glacier-sync.service; do
  if [ ! -f "$HERE/$required" ]; then
    echo "Missing Glacier Sync source: $required" >&2
    exit 1
  fi
done
command -v python3 >/dev/null || { echo 'Python 3 required' >&2; exit 1; }
command -v systemctl >/dev/null || { echo 'systemd required' >&2; exit 1; }

if ! id glacier-sync >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/glacier-sync --shell /usr/sbin/nologin glacier-sync
fi
install -d -o glacier-sync -g glacier-sync -m 0700 /var/lib/glacier-sync
install -d -o root -g root -m 0755 /opt/glacier-sync
install -m 0644 "$HERE/server.py" /opt/glacier-sync/server.py
install -m 0644 "$HERE/requirements.txt" /opt/glacier-sync/requirements.txt
if [ ! -x /opt/glacier-sync/.venv/bin/python ]; then
  python3 -m venv /opt/glacier-sync/.venv
fi
/opt/glacier-sync/.venv/bin/python -m pip install --disable-pip-version-check \
  -r /opt/glacier-sync/requirements.txt

install -d -o root -g root -m 0700 /etc/glacier-sync
if [ ! -f /etc/glacier-sync/secrets.env ]; then
  command -v openssl >/dev/null || { echo 'openssl required' >&2; exit 1; }
  invite="$(openssl rand -hex 32)"
  printf 'GLACIER_SYNC_INVITE=%s\nGLACIER_SYNC_DB=/var/lib/glacier-sync/sync.sqlite3\n' \
    "$invite" > /etc/glacier-sync/secrets.env
  chmod 0600 /etc/glacier-sync/secrets.env
  unset invite
  echo "Generated a private registration invite at /etc/glacier-sync/secrets.env (not printed)."
else
  echo "Preserved existing private registration invite and database settings."
fi
install -m 0644 "$HERE/glacier-sync.service" /etc/systemd/system/glacier-sync.service
systemctl daemon-reload
systemctl enable --now glacier-sync.service
systemctl restart glacier-sync.service
if systemctl is-active --quiet glacier-sync.service; then
  echo "Glacier Sync service active; checking private health endpoint."
  if curl --fail --silent --show-error --max-time 7 \
      http://127.0.0.1:18991/health | grep -q '"status":"ok"'; then
    echo "Glacier Sync backend healthy on 127.0.0.1:18991."
  else
    echo "Glacier Sync service active but /health did not return OK." >&2
    exit 1
  fi
else
  echo "Glacier Sync did not start. Inspect: journalctl -u glacier-sync -n 40" >&2
  exit 1
fi
echo "NEXT: configure TLS / Nginx vhost sync.borealos.cn, then check HTTPS /health."
echo "Do not publicly expose port 18991 or print the private invite."
