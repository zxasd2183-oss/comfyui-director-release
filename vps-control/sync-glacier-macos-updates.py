#!/usr/bin/env python3
"""VPS-side mirror of Ed25519-authorized Glacier macOS DMG releases.

Mac clients contact ONLY the owner's jipite.borealos.cn HTTPS endpoint.
This server-side job contacts GitHub, verifies the offline-signed manifest,
downloads exact release assets, and atomically publishes validated bytes.
It requires no GitHub credentials and no signing private key.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import urllib.parse
import urllib.request

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

FEED_SOURCE = (
    "https://raw.githubusercontent.com/zxasd2183-oss/comfyui-director-release/"
    "glacier-browser-updates/channels/macos-arm64.json"
)
RELEASE_BASE = (
    "https://github.com/zxasd2183-oss/comfyui-director-release/"
    "releases/download/"
)
PUBLIC_BASE = "https://jipite.borealos.cn/glacier-updates/"
KEY_ID = "cf9452226375ff7d"
PUB = bytes.fromhex("7c375bfd04b4941a662a9a66e9c3f980653cb01b9e5df286ec651eca84e26dab")
FIELDS = {"channel","version","url","sha256","size","notes","key_id","signature"}
VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ALLOWED = frozenset((
    "raw.githubusercontent.com", "github.com", "release-assets.githubusercontent.com",
    "objects.githubusercontent.com", "github-releases.githubusercontent.com",
))
LIMIT = 1_073_741_824


class RestrictedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        assert_allowed(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(RestrictedRedirects())


def assert_allowed(url):
    p = urllib.parse.urlsplit(url)
    if (p.scheme != "https" or p.hostname not in ALLOWED or p.port not in (None,443)
            or p.username or p.password or p.fragment):
        raise ValueError("Refusing a redirect outside the allowed HTTPS release sources")


def fetch(url,timeout=60):
    assert_allowed(url)
    req = urllib.request.Request(url,headers={"User-Agent":"Glacier-Mac-VPS-Mirror/1.0"})
    return OPENER.open(req,timeout=timeout)


def _unique(pairs):
    value={}
    for k,v in pairs:
        if k in value:
            raise ValueError("Duplicate JSON update manifest key")
        value[k]=v
    return value


def canonical(doc):
    return json.dumps(doc,ensure_ascii=False,sort_keys=True,
                      separators=(",",":"),allow_nan=False).encode("utf-8")


def validate_signed_manifest(raw):
    if len(raw)>65536:
        raise ValueError("Signed update manifest too large")
    doc = json.loads(raw.decode("utf-8-sig"),object_pairs_hook=_unique)
    if not isinstance(doc,dict) or set(doc)!=FIELDS:
        raise ValueError("Signed manifest schema mismatch")
    if doc["channel"]!="macos-arm64" or doc["key_id"]!=KEY_ID:
        raise ValueError("Wrong Glacier update channel or signing key")
    sig=doc["signature"]
    if not isinstance(sig,str):
        raise ValueError("Manifest missing signature")
    try:
        signature=base64.b64decode(sig,validate=True)
    except (binascii.Error,ValueError) as exc:
        raise ValueError("Invalid signature encoding") from exc
    if len(signature)!=64:
        raise ValueError("Unexpected Ed25519 signature length")
    payload={k:v for k,v in doc.items() if k!="signature"}
    try:
        Ed25519PublicKey.from_public_bytes(PUB).verify(signature,canonical(payload))
    except InvalidSignature as exc:
        raise ValueError("Untrusted signed manifest: abort VPS mirror") from exc
    ver=doc["version"]
    if not isinstance(ver,str) or not VERSION.fullmatch(ver):
        raise ValueError("Invalid release version")
    name=f"GlacierBrowser-v{ver}-macOS-AppleSilicon.dmg"
    if doc["url"]!=PUBLIC_BASE+name:
        raise ValueError("Manifest is not pinned to owner VPS URL")
    if type(doc["size"]) is not int or not 1_000_000<=doc["size"]<=LIMIT:
        raise ValueError("Invalid release size")
    if not isinstance(doc["sha256"],str) or not SHA256.fullmatch(doc["sha256"]):
        raise ValueError("Invalid SHA256")
    if not isinstance(doc["notes"],str) or len(doc["notes"])>5000:
        raise ValueError("Invalid release notes")
    return doc,name


def sha256_file(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()


def atomic_write(path,data):
    fd,tmp=tempfile.mkstemp(prefix=".glacier-",dir=path.parent)
    tmp=Path(tmp)
    try:
        with os.fdopen(fd,"wb") as out:
            out.write(data);out.flush();os.fsync(out.fileno())
        os.chmod(tmp,0o644)
        os.replace(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)


def mirror(directory):
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("Mirror destination must be a real directory")
    lock=directory/".sync.lock"
    fd=os.open(str(lock),os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with fetch(FEED_SOURCE,20) as response:
            raw=response.read(65537)
        doc,name=validate_signed_manifest(raw)
        current=directory/"macos-arm64.json"
        if current.is_symlink():
            raise ValueError("Current manifest must not be symlink")
        if current.exists():
            existing, _=validate_signed_manifest(current.read_bytes())
            before=tuple(map(int,existing["version"].split(".")))
            after=tuple(map(int,doc["version"].split(".")))
            if after<before:
                raise ValueError("Refusing a signed release rollback")
        target=directory/name
        if target.is_symlink():
            raise ValueError("DMG target must not be a symlink")
        valid=(target.is_file() and target.stat().st_size==doc["size"]
               and sha256_file(target)==doc["sha256"])
        if not valid:
            url=RELEASE_BASE+f"glacier-macos-v{doc['version']}/"+name
            download_fd,tempfile_name=tempfile.mkstemp(prefix=".glacier-dmg-",dir=directory)
            temp=Path(tempfile_name)
            try:
                with os.fdopen(download_fd,"wb") as out,fetch(url,50) as response:
                    count=0; digest=hashlib.sha256()
                    while True:
                        chunk=response.read(1024*1024)
                        if not chunk:break
                        count+=len(chunk)
                        if count>doc["size"]:
                            raise ValueError("DMG download exceeded signed byte count")
                        digest.update(chunk);out.write(chunk)
                    out.flush();os.fsync(out.fileno())
                if count!=doc["size"] or digest.hexdigest()!=doc["sha256"]:
                    raise ValueError("Mac DMG does not match offline-signed manifest")
                os.chmod(temp,0o644)
                os.replace(temp,target)
            finally:
                temp.unlink(missing_ok=True)
        atomic_write(current,raw)
        print("Glacier macOS VPS mirror ready:",doc["version"],flush=True)
        print("DMG:",PUBLIC_BASE+name,flush=True)
        print("Update feed:",PUBLIC_BASE+"macos-arm64.json",flush=True)
    finally:
        os.close(fd)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--directory",type=Path,default=Path("/var/lib/glacier-macos-updates"))
    args=parser.parse_args()
    try:
        mirror(args.directory)
        return 0
    except Exception as exc:
        print("Glacier mirror refused update: "+str(exc),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
