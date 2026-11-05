#!/usr/bin/env bash
# Director Studio V0.9.1 -- explicit owner-approved Microsoft Web sign-in.
# No GPU, power, mobile device, approval DB writes or Nginx vhost edits.
# Old Basic Auth remains until SSO gate is demonstrably active.
set -Eeuo pipefail
umask 077
die(){ echo "ERROR: $*" >&2; exit 2; }
[[ "$EUID" -eq 0 ]] || die "Run with sudo on the trusted VPS"
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST=/opt/director-studio
DROPIN=/etc/systemd/system/director-studio.service.d/microsoft.conf
VENV=$DEST/.venv
systemctl is-active --quiet director-studio || die "V0.9 Studio must be active"
systemctl is-active --quiet director-mobile-v06 || die "Jipite personal owner API not active"
systemctl is-active --quiet nginx || die "Nginx must be active"
[[ -f "$SRC/studio_identity.py" && -f "$SRC/setup_microsoft_sso.py" \
   && -f "$SRC/director-studio-microsoft.service.conf" \
   && -f "$SRC/promote_microsoft_nginx.py" ]] || die "Missing V0.9.1 source files"
[[ -f /etc/nginx/snippets/director-studio.conf ]] || \
  die "First deploy the existing protected /studio/ Basic Auth route"
if cmp -s /etc/nginx/snippets/director-studio.conf \
    "$SRC/nginx-jipite-studio-microsoft.conf"; then
  [[ -f "$DROPIN" ]] || die "Microsoft route enabled without service guard; manual recovery required"
elif ! cmp -s /etc/nginx/snippets/director-studio.conf \
    "$SRC/nginx-jipite-studio.conf"; then
  die "Unexpected Studio Nginx route; refusing to overwrite it"
fi
[[ ! -L "$DEST" && -d "$DEST" ]] || die "Studio destination unsafe"
[[ ! -L "$VENV" ]] || die "Refusing symlinked Studio Python environment"
if [[ -e "$DROPIN" || -L "$DROPIN" ]]; then
  # No silent reconfiguration of potentially live Microsoft sessions.
  if [[ -f "$DROPIN" ]] && cmp -s "$DROPIN" "$SRC/director-studio-microsoft.service.conf"; then
    echo "Microsoft systemd unit already configured; checking service"
  else
    die "Existing Microsoft systemd dropin differs; manual review required"
  fi
fi
python3 -m unittest discover -s "$SRC/tests" -p 'test_*.py' -q

# Upgrade private app WITHOUT changing Basic Auth, GPU, or Nginx.
bash "$SRC/upgrade-v09.sh"
if [[ ! -x "$VENV/bin/python" ]]; then
    python3 -m venv "$VENV" || die "python3-venv missing; install it before retry"
fi
"$VENV/bin/python" -m pip install --disable-pip-version-check \
    'msal==1.39.0' 'PyJWT[crypto]>=2.10,<3'
"$VENV/bin/python" -c 'import msal,jwt; print("PASS: supported Microsoft SDK and JWT signature verifier installed")'

# Only the private root terminal receives the confidential Web app secret.
if [[ ! -f /etc/director-studio/msweb.json ]]; then
  echo "Your existing Microsoft personal app registration must include this"
  echo "  Web platform redirect URI (exact):"
  echo "  https://jipite.borealos.cn/studio/auth/callback"
  echo "Enter the NEW confidential Web client secret VALUE (not the secret ID)."
  python3 "$SRC/setup_microsoft_sso.py"
else
  [[ ! -L /etc/director-studio/msweb.json ]] || die "Symlinked credential refused"
  [[ "$(stat -c '%a:%u' /etc/director-studio/msweb.json)" == "600:0" ]] || \
    die "Existing Microsoft credential permissions unsafe"
  echo "Existing root-only Web credential reused"
fi
"$VENV/bin/python" -m py_compile "$DEST/studio_server.py" "$DEST/studio_identity.py"

mkdir -p "$(dirname "$DROPIN")"
NEW_DROPIN=0
if [[ ! -f "$DROPIN" ]]; then
  install -o root -g root -m 0644 \
    "$SRC/director-studio-microsoft.service.conf" "$DROPIN"
  NEW_DROPIN=1
fi
COMMITTED=0
restore(){
  local code="$1"
  trap - EXIT
  if (( ! COMMITTED )); then
    echo "Microsoft SSO promotion failed; keeping/reverting to Basic Auth." >&2
    if (( NEW_DROPIN )); then
      rm -f "$DROPIN"
    fi
    systemctl daemon-reload || :
    systemctl restart director-studio || :
    echo "If Nginx has an unexpected partial state, check its snippet locally." >&2
  fi
  exit "$code"
}
trap 'restore $?' EXIT
systemctl daemon-reload
systemctl restart director-studio
systemctl is-active --quiet director-studio || die "SSO Studio service failed"

# A successful Microsoft redirect and a denied anonymous snapshot are both
# REQUIRED before removing Nginx Basic Auth. No need to submit real tokens.
python3 "$SRC/promote_microsoft_nginx.py"

COMMITTED=1
echo "SUCCESS: Director Studio Microsoft owner SSO gate enabled."
echo "URL: https://jipite.borealos.cn/studio/"
echo "Only your original Jipite Microsoft owner subject is authorized."
echo "Session: Secure, HttpOnly, SameSite=Lax, memory-only, auto-expiring."
echo "The separate phone biometric GPU power approval is unchanged."
echo "No GPU boot, ComfyUI jobs, phone pairing or cloud credentials touched."
