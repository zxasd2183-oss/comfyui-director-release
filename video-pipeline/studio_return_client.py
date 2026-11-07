"""Pinned TLS upload of GPU MP4 to Studio; no Microsoft cookie stored on GPU."""
from __future__ import annotations
import base64
import hashlib
import json
from pathlib import Path
import re
import stat
import urllib.error
import urllib.request

BASE="https://jipite.borealos.cn/studio/api/v1/gpu-return/"
CHUNK=786432
LIMIT=16384


class ReturnClientError(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ReturnClientError("Studio return redirect rejected")


OPENER=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())


def read_token_file(path):
    source=Path(path)
    if not source.is_file() or source.is_symlink():
        raise ReturnClientError("GPU return token file missing or unsafe")
    info=source.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size>256:
        raise ReturnClientError("GPU return token must be a private 0600 file")
    token=source.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,120}",token):
        raise ReturnClientError("GPU return token invalid")
    return token


def send(command,body,token,*,opener=None):
    if command not in ("start","chunk","finish"):
        raise ReturnClientError("Unknown return command")
    payload=json.dumps(body,separators=(",",":")).encode()
    if len(payload)>CHUNK*4//3+4096:
        raise ReturnClientError("GPU return payload too large")
    url=BASE+command
    req=urllib.request.Request(url,data=payload,method="POST",headers={
        "Authorization":"Bearer "+token,
        "Content-Type":"application/json","Accept":"application/json"})
    try:
        with (opener or OPENER).open(req,timeout=90) as res:
            if res.geturl()!=url:
                raise ReturnClientError("Studio return redirect rejected")
            raw=res.read(LIMIT+1)
        if len(raw)>LIMIT:
            raise ReturnClientError("Studio return response too large")
        data=json.loads(raw)
        if not isinstance(data,dict) or data.get("ok") is not True:
            raise ReturnClientError("Studio rejected GPU return")
        return data
    except urllib.error.HTTPError as error:
        raise ReturnClientError("Studio return HTTP "+str(error.code)) from None
    except (OSError,UnicodeError,ValueError) as error:
        if isinstance(error,ReturnClientError):
            raise
        raise ReturnClientError("Studio return transport unavailable") from None


def return_shot(plan,results_dir,shot_id,token,*,sender=send):
    epi=plan.get("studio_episode_handoff")
    single=plan.get("studio_handoff")
    receipts=epi.get("shot_receipts") if isinstance(epi,dict) else (
        [single] if isinstance(single,dict) else None)
    if not isinstance(receipts,list):
        raise ReturnClientError("Studio video handoff receipts missing")
    found=[x for x in receipts if isinstance(x,dict) and x.get("shot_id")==shot_id]
    if len(found)!=1:
        raise ReturnClientError("Studio receipt missing or duplicated")
    receipt=found[0]
    folder=Path(results_dir)/shot_id
    manifest_file=folder/"manifest.json"
    if folder.is_symlink() or manifest_file.is_symlink():
        raise ReturnClientError("Unsafe output directory")
    manifest=json.loads(manifest_file.read_text(encoding="utf-8"))
    downloaded=manifest.get("downloaded")
    if manifest.get("shot_id")!=shot_id or not isinstance(downloaded,list):
        raise ReturnClientError("Incorrect GPU output manifest")
    movies=[x for x in downloaded if isinstance(x,dict) and isinstance(x.get("file"),str)
            and Path(x["file"]).suffix.lower()==".mp4"]
    if len(movies)!=1:
        raise ReturnClientError("Exactly one downloaded MP4 required")
    info=movies[0]
    filename=info["file"]
    if (filename in (".","..") or "/" in filename or "\\" in filename or
            "\x00" in filename or len(filename)>200):
        raise ReturnClientError("Unsafe MP4 filename")
    movie=folder/filename
    if movie.is_symlink() or not movie.is_file():
        raise ReturnClientError("Missing GPU MP4")
    size=movie.stat().st_size
    if not 128<=size<=250_000_000:
        raise ReturnClientError("GPU MP4 size outside Studio limits")
    digest=hashlib.sha256()
    with movie.open("rb") as stream:
        for part in iter(lambda:stream.read(1<<20),b""):
            digest.update(part)
    sha=digest.hexdigest()
    if info.get("sha256")!=sha or info.get("bytes")!=size:
        raise ReturnClientError("GPU MP4 integrity mismatch")
    begun=sender("start",{
        "project_id":receipt.get("project_id"),"episode_id":receipt.get("episode_id"),
        "shot_id":shot_id,"plan_revision":receipt.get("video_revision"),
        "package_sha256":receipt.get("package_sha256"),"file_sha256":sha,
        "size_bytes":size,"prompt_id":manifest.get("prompt_id"),
    },token)
    if begun.get("already_imported") is True:
        return {"ok":True,"shot_id":shot_id,"already_imported":True,
                "take_id":begun.get("take_id")}
    uid=begun.get("upload_id")
    offset=begun.get("received_bytes")
    if (not isinstance(uid,str) or not re.fullmatch(r"UP_[0-9a-f]{32}",uid)
            or type(offset) is not int or not 0<=offset<=size):
        raise ReturnClientError("Studio resume state invalid")
    with movie.open("rb") as handle:
        handle.seek(offset)
        while offset<size:
            chunk=handle.read(min(CHUNK,size-offset))
            reply=sender("chunk",{
                "upload_id":uid,"offset":offset,
                "chunk_base64":base64.b64encode(chunk).decode("ascii")},token)
            if reply.get("received_bytes")!=offset+len(chunk):
                raise ReturnClientError("Studio chunk offset mismatch")
            offset+=len(chunk)
    finished=sender("finish",{"upload_id":uid},token)
    if finished.get("status")!="in_review":
        raise ReturnClientError("Studio did not register reviewable MP4")
    return {"ok":True,"shot_id":shot_id,"take_id":finished.get("take_id"),
            "status":"in_review","already_imported":False}
