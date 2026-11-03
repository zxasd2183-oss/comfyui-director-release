#!/usr/bin/env bash
set -euo pipefail
if [[ ${EUID} -ne 0 ]]; then echo 'Run: sudo bash install-ubuntu.sh' >&2; exit 1; fi
BASE_DIR=$(cd "$(dirname "$0")" && pwd)
if ! command -v python3 >/dev/null; then echo 'Python 3 required' >&2; exit 1; fi
if ! python3 -m venv --help >/dev/null 2>&1; then
  echo 'Please install python3-venv first: sudo apt-get install python3-venv' >&2; exit 1
fi
id directorctl >/dev/null 2>&1 || useradd --system --home /opt/comfyui-director-control --shell /usr/sbin/nologin directorctl
mkdir -p /opt/comfyui-director-control
install -o root -g root -m 0644 "$BASE_DIR/api.py" /opt/comfyui-director-control/api.py
install -o root -g root -m 0644 "$BASE_DIR/app.py" /opt/comfyui-director-control/app.py
install -o root -g root -m 0644 "$BASE_DIR/requirements.txt" /opt/comfyui-director-control/requirements.txt
python3 -m venv /opt/comfyui-director-control/.venv
/opt/comfyui-director-control/.venv/bin/pip install --disable-pip-version-check -r /opt/comfyui-director-control/requirements.txt
if [[ ! -f /etc/comfyui-director-control.env ]]; then
  cat > /etc/comfyui-director-control.env <<'ENV'
# Edit as root: sudoedit /etc/comfyui-director-control.env
# Keys from CompShare account > API Keys (NOT a Model API key)
COMP_PUBLIC_KEY=
COMP_PRIVATE_KEY=
COMP_UHOST_ID=
COMP_REGION=cn-wlcb
COMP_ZONE=
DIRECTOR_VPS_PORT=8890
ENV
  chmod 600 /etc/comfyui-director-control.env
fi
install -o root -g root -m 0644 "$BASE_DIR/director-vps-control.service" /etc/systemd/system/director-vps-control.service
systemctl daemon-reload
systemctl enable --now director-vps-control
printf '\nInstalled read-only VPS controller at localhost:8890\n'
printf 'Do NOT expose 8890 publicly without OAuth or an authenticated reverse proxy.\n'
printf 'Configure credentials: sudoedit /etc/comfyui-director-control.env\n'
printf 'Restart afterwards: sudo systemctl restart director-vps-control\n'
printf 'Logs: sudo journalctl -u director-vps-control -n 30 --no-pager\n'
