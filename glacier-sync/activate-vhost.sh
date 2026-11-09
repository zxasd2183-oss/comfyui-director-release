#!/usr/bin/env bash
# Activate Glacier Sync in its existing dedicated 8443 server block.
# This script intentionally refuses to rewrite an unknown Nginx layout.
set -Eeuo pipefail
[ "${EUID}" -eq 0 ] || { echo 'Run as root' >&2; exit 1; }
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET=/etc/nginx/conf.d/zz-new-domains.conf
SNIPPET=/etc/nginx/snippets/glacier-sync.conf
[ -f "$TARGET" ] || { echo "Missing $TARGET" >&2; exit 1; }
[ -f "$SRC/nginx-sync.snippet.conf" ] || { echo "Missing snippet source" >&2; exit 1; }
nginx -t
install -d -m 0755 /etc/nginx/snippets
install -m 0644 "$SRC/nginx-sync.snippet.conf" "$SNIPPET"
backup="$TARGET.glacier-backup.$(date +%Y%m%d%H%M%S)"
cp -p "$TARGET" "$backup"
if ! python3 - "$TARGET" <<'PY'
import pathlib, re, sys
path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
lines = text.splitlines(keepends=True)
# Parse only top-level server blocks; do not alter the other five domains.
depth = 0
start = None
blocks = []
for i, line in enumerate(lines):
    uncommented = line.split("#",1)[0]
    if depth == 0 and re.match(r"^\s*server\s*\{", uncommented):
        start = i
    depth += uncommented.count("{") - uncommented.count("}")
    if depth < 0:
        raise SystemExit("Nginx braces unbalanced; aborting")
    if depth == 0 and start is not None:
        blocks.append((start,i+1))
        start = None
if depth:
    raise SystemExit("Nginx braces unbalanced; aborting")
matches = []
for begin,end in blocks:
    block = "".join(lines[begin:end])
    if (re.search(r"(?m)^\s*server_name\s+[^;]*\bsync\.borealos\.cn\b[^;]*;",block)
            and re.search(r"(?m)^\s*listen\s+[^;]*\b8443\b[^;]*;",block)):
        matches.append((begin,end))
if len(matches) != 1:
    raise SystemExit(f"Expected one sync 8443 server, found {len(matches)}; aborting")
begin,end=matches[0]
block=lines[begin:end]
if any("include /etc/nginx/snippets/glacier-sync.conf;" in line for line in block):
    print("Glacier snippet already enabled; no change")
    sys.exit(0)
if any(re.search(r"\blocation\s+", line.split("#",1)[0]) for line in block):
    raise SystemExit("Sync placeholder has an existing location: refuse automatic rewrite")
# Placeholder server may contain a root directive; remove ONLY the known root.
block=[line for line in block if not re.match(
    r"^\s*root\s+/var/www/placeholder\s*;\s*(?:#.*)?$",line)]
# Also remove placeholder-only index configuration; none is needed by the API.
block=[line for line in block if not re.match(
    r"^\s*index\s+index\.html\s*;\s*(?:#.*)?$",line)]
# insert just before its closing brace, retaining existing TLS directives.
closing = next((i for i in range(len(block)-1,-1,-1)
                if re.match(r"^\s*}\s*(?:#.*)?$",block[i])),None)
if closing is None:
    raise SystemExit("Cannot locate closing brace for sync server")
block.insert(closing, "    include /etc/nginx/snippets/glacier-sync.conf;\n")
updated=lines[:begin]+block+lines[end:]
path.write_text("".join(updated),encoding="utf-8")
print("Enabled sync snippet in only the existing 8443 sync server.")
PY
then
  cp -p "$backup" "$TARGET"
  echo "Refused unsafe Nginx edit; original configuration restored." >&2
  exit 1
fi
if ! nginx -t; then
  cp -p "$backup" "$TARGET"
  nginx -t || true
  echo "Nginx validation failed; original configuration restored." >&2
  exit 1
fi
systemctl reload nginx
echo "Glacier Sync vhost enabled. Other domains' server blocks left untouched."
if curl --fail --silent --show-error --max-time 12 https://sync.borealos.cn/health |
    grep -q '"status":"ok"'; then
  echo "Verified external HTTPS Glacier Sync health."
else
  echo "HTTPS health not confirmed. Check TLS routing and status manually." >&2
  exit 2
fi
