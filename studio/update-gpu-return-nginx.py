#!/usr/bin/env python3
"""Only add the reviewed GPU bearer upload location to the existing owner SSO proxy."""
from pathlib import Path
import os
import subprocess
import tempfile

LIVE=Path("/etc/nginx/snippets/director-studio.conf")
HERE=Path(__file__).resolve().parent

def install():
    if os.geteuid()!=0:
        raise RuntimeError("sudo_required")
    if not LIVE.is_file() or LIVE.is_symlink():
        raise RuntimeError("studio_nginx_snippet_missing_or_symlink")
    old=(HERE/"nginx-jipite-studio-microsoft-before-gpu.conf").read_bytes()
    new=(HERE/"nginx-jipite-studio-microsoft.conf").read_bytes()
    previous=LIVE.read_bytes()
    if previous==new:
        subprocess.run(["nginx","-t"],check=True)
        return
    if previous!=old:
        raise RuntimeError("unexpected_studio_microsoft_nginx_config")
    if (b'proxy_set_header Authorization $http_authorization;' not in new or
            b'proxy_set_header Authorization "";' not in new):
        raise RuntimeError("gpu_return_nginx_auth_policy_invalid")
    fd,name=tempfile.mkstemp(prefix=".studio-gpu-return-backup-",dir=str(LIVE.parent))
    os.chmod(name,0o600)
    with os.fdopen(fd,"wb") as stream:
        stream.write(previous)
    try:
        LIVE.write_bytes(new)
        subprocess.run(["nginx","-t"],check=True)
        subprocess.run(["systemctl","reload","nginx"],check=True)
    except BaseException:
        LIVE.write_bytes(previous)
        subprocess.run(["nginx","-t"],check=True)
        subprocess.run(["systemctl","reload","nginx"],check=True)
        raise
    print("GPU return upload route installed. Existing owner authentication retained.")
    print("Secure Nginx backup:",name)

if __name__=="__main__":
    install()
