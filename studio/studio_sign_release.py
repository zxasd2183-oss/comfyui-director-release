"""Sign pinned Studio code/UI archive; never include project data or secrets."""
from __future__ import annotations
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from studio_signed_updater import (FORMAT, FILES, HEX, MAX_FILE,
                                   MAX_PACKAGE, UpdateError, canon, version)

def sign(version_str, source, destination, private_hex, public_hex):
    version(version_str)
    if (not isinstance(private_hex,str) or not HEX.fullmatch(private_hex)
            or not isinstance(public_hex,str) or not HEX.fullmatch(public_hex)):
        raise UpdateError("signing_key_missing")
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_hex))
    derived = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    if derived != public_hex:
        raise UpdateError("signing_key_drift")
    source, destination = Path(source), Path(destination)
    if not source.is_dir() or destination.exists():
        raise UpdateError("source_or_destination_invalid")
    files = {}
    for filename in FILES:
        path = source / filename
        if path.is_symlink() or not path.is_file():
            raise UpdateError("source_missing_"+filename)
        data = path.read_bytes()
        if not 0 < len(data) <= MAX_FILE:
            raise UpdateError("source_too_large")
        if filename.endswith(".py"):
            compile(data, filename,"exec",dont_inherit=True)
        elif b"\x00" in data:
            raise UpdateError("unsafe_noncode_asset")
        files[filename] = data
    if files["studio_server.py"].decode("utf-8").count(
        'STUDIO_CODE_VERSION = "'+version_str+'"') != 1:
        raise UpdateError("studio_code_version_inconsistent")
    destination.mkdir()
    archive = destination / ("director-studio-v"+version_str+".zip")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as out:
        for name in FILES:
            entry=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0))
            entry.compress_type=zipfile.ZIP_DEFLATED
            entry.external_attr=0o100644 << 16
            out.writestr(entry,files[name],compress_type=zipfile.ZIP_DEFLATED)
    blob=archive.read_bytes()
    if len(blob)>MAX_PACKAGE: raise UpdateError("package_too_large")
    payload={"format":FORMAT,"version":version_str,"archive_sha256":
             hashlib.sha256(blob).hexdigest(),"archive_size":len(blob)}
    document={**payload,"signature":key.sign(canon(payload)).hex()}
    (destination/"channel.json").write_text(
        json.dumps(document,sort_keys=True,indent=2)+"\n",encoding="ascii")
    return payload

if __name__ == "__main__":
    if len(sys.argv)!=4:
        raise SystemExit("usage: studio_sign_release.py <x.y.z> <studio> <new_output>")
    print(json.dumps(sign(sys.argv[1],sys.argv[2],sys.argv[3],
          os.environ.get("DIRECTOR_UE_SIGNING_PRIVATE_HEX",""),
          os.environ.get("DIRECTOR_UE_SIGNING_PUBLIC_HEX",""))))
