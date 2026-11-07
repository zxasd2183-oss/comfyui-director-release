"""Director Studio V0.8: SSH-only real-time supervisory HTTP console.

Service binds 127.0.0.1:8900. Never expose it via Nginx before implementing
owner authentication. Studio interventions edit an audited scheduling ledger,
NOT the live ComfyUI queue or GPU power.
"""
from __future__ import annotations

import json
import os
import sqlite3
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl

from studio_core import StudioError, connect, decide, snapshot
from studio_backend import query
from studio_identity import (from_systemd, cookies, COOKIE_SID, COOKIE_STATE,
    state_cookie, session_cookie, clear_cookie, IdentityError,
    ALLOWED_CALLBACK_FIELDS)
from production_core import (
    open_db as open_production, dashboard_from_path,
    episode_detail_from_path, ProductionError
)
from production_web import create_from_web, ProductionWebError, operator_from_verified_session
from visual_library import (VisualError, MAX_POST_BYTES, prepare_schema,
                            list_visuals, upload_visual, select_visual, read_visual,
                            ingest_chatgpt_image)
from character_library import (
    CharacterError, prepare_schema as prepare_characters, list_characters,
    create_character, update_character, link_visual as link_character_visual,
    set_master as approve_character_master
)
from character_library_v2 import (
    prepare_schema as prepare_character_v2, list_assets as list_character_v2,
    create_asset as create_character_v2_asset,
    revise_asset as revise_character_v2_asset,
    review_asset as review_character_v2_asset,
)
from shot_character_bindings import (
    prepare_schema as prepare_shot_character,
    list_bindings as list_shot_character,
    bind_character as save_shot_character,
)
from scene_library import (
    SceneError, prepare_schema as prepare_scenes, list_scenes,
    create_scene, update_scene, link_scene_visual, review_scene,
)
from production_workflows import (
    WorkflowError, prepare_schema as prepare_workflows,
    list_units as list_workflow_units,
    save_unit as save_workflow_unit, review_unit as review_workflow_unit,
    list_reviews as list_workflow_reviews,
    get_episode_readiness as get_workflow_readiness,
    get_video_handoff_package as get_workflow_handoff,
    get_episode_video_handoffs as get_workflow_episode_handoffs,
)
from video_results import (
    VideoResultError, CHUNK_BYTES as VIDEO_CHUNK_BYTES,
    prepare_schema as prepare_video_results,
    begin_upload as begin_video_upload,
    append_chunk as append_video_chunk,
    finish_upload as finish_video_upload,
    list_takes as list_video_takes,
    get_take_file as get_video_take_file,
    review_take as review_video_take
)
from picture_cuts import (
    PictureCutError, prepare_schema as prepare_picture_cuts,
    get_readiness as get_picture_cut_readiness,
    list_cuts as list_picture_cuts,
    get_cut_file as get_picture_cut_file,
    review_cut as review_picture_cut
)
from picture_cut_jobs import (
    PictureJobError, prepare_schema as prepare_picture_cut_jobs,
    enqueue as enqueue_picture_cut,
    list_jobs as list_picture_cut_jobs,
    worker_loop as picture_cut_worker_loop
)
from audio_stems import (
    AudioError, MAX_BYTES as MAX_AUDIO_BYTES,
    prepare_schema as prepare_audio_stems,
    start as begin_audio_upload,
    append as append_audio_chunk,
    finish as finish_audio_upload,
    list_stems as list_audio_stems,
    get_stem_file as get_audio_stem_file,
    review as review_audio_stem
)
from audio_master import (
    MasterError, prepare_schema as prepare_av_masters,
    readiness as get_av_master_readiness,
    list_masters as list_av_masters,
    get_file as get_av_master_file,
    review as review_av_master
)
from audio_master_jobs import (
    MasterJobError, prepare_schema as prepare_av_master_jobs,
    enqueue as enqueue_av_master,
    list_jobs as list_av_master_jobs,
    media_worker_loop
)
from subtitle_tracks import (
    SubtitleError, prepare_schema as prepare_subtitle_tracks,
    save as save_subtitle_track, review as review_subtitle_track,
    list_tracks as list_subtitle_tracks,
    get_file as get_subtitle_file, as_webvtt
)
from release_candidates import (
    ReleaseError, prepare_schema as prepare_release_candidates,
    readiness as get_release_readiness,
    list_candidates as list_release_candidates,
    get_file as get_release_file,
    get_private_delivery_receipt,
    review as review_release_candidate
)
from release_jobs import (
    ReleaseJobError, prepare_schema as prepare_release_jobs,
    enqueue as enqueue_release_job, list_jobs as list_release_jobs
)
from studio_brain import (
    BrainAuthenticator, BrainError, systemd_secret,
    execute as execute_brain, BRAIN_PATH, MAX_BODY as MAX_BRAIN_BODY
)

BASE = Path(__file__).resolve().parent
HOSTS = {"127.0.0.1:8900", "localhost:8900"}
MAX_BODY = 8192
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; "
       "connect-src 'self'; img-src 'self' data:; media-src 'self'; "
       "base-uri 'none'; frame-ancestors 'none'")

# Fixed vocabulary only. Never log arbitrary keys because an attacker can put
# tokens, newlines or PII in an OAuth query *parameter name* as well as a value.
SAFE_CALLBACK_FIELDS = frozenset({
    "code", "state", "session_state", "error", "error_description",
    "error_uri", "iss", "client_info",
})


def callback_fields_for_log(raw_query):
    """Bounded diagnostic of parameter NAMES only, never any OAuth values."""
    if not isinstance(raw_query, str) or len(raw_query) > 16384:
        return "param_names=oversized param_count=unknown unknown_count=unknown duplicates=unknown"
    try:
        pairs = parse_qsl(raw_query, keep_blank_values=True, max_num_fields=32)
    except (ValueError, UnicodeError):
        return "param_names=too_many param_count=over_limit unknown_count=unknown duplicates=unknown"
    names = [name for name, _ in pairs]
    safe = sorted(set(names).intersection(SAFE_CALLBACK_FIELDS))
    unknown = sum(name not in SAFE_CALLBACK_FIELDS for name in names)
    unsupported = sum(name not in ALLOWED_CALLBACK_FIELDS for name in names)
    if unknown:
        safe.append("other")
    duplicates = len(names) - len(set(names))
    return ("param_names=" + (",".join(safe) if safe else "none")
            + " param_count=" + str(len(names))
            + " unknown_count=" + str(unknown)
            + " unsupported_count=" + str(unsupported)
            + " duplicates=" + str(duplicates))


class Poller:
    def __init__(self, interval=5, probe=query):
        self.interval, self.probe = interval, probe
        self.lock = threading.Lock()
        self.data = {
            "gpu_power": {"ok": False, "reason": "not_checked"},
            "comfy_queue": {"ok": False, "reason": "not_checked"},
            "last_checked": None,
        }
        self.running = True

    def sample(self):
        result = {}
        for name, tool in (("gpu_power", "get_gpu_power_status"),
                           ("comfy_queue", "get_queue_summary")):
            try:
                value = self.probe(tool)
                result[name] = value if isinstance(value, dict) else {
                    "ok": False, "reason": "unexpected_backend_result"}
            except Exception:
                result[name] = {"ok": False, "reason": "backend_unavailable"}
        with self.lock:
            self.data = {**result, "last_checked": int(time.time())}

    def loop(self):
        while self.running:
            self.sample()
            for _ in range(int(self.interval * 10)):
                if not self.running:
                    break
                time.sleep(0.1)

    def current(self):
        with self.lock:
            return dict(self.data)


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, db_path, poller=None, bind=("127.0.0.1", 8900)):
        if bind[0] != "127.0.0.1":
            raise RuntimeError("Only 127.0.0.1 binding is permitted")
        self.db_path = db_path
        self.production_db_path = str(Path(db_path).with_name("production.sqlite"))
        self.poller = poller if poller is not None else Poller()
        self.csrf_token = secrets.token_urlsafe(32)
        self.video_upload_lock = threading.Lock()
        self.audio_upload_lock = threading.Lock()
        self.identity = from_systemd()
        # Private signed Hub->Studio channel, independent from browser OIDC.
        self.brain_auth = BrainAuthenticator(systemd_secret())
        self.is_running = True
        with closing(connect(self.db_path)):
            pass
        # Independent V0.9 database; legacy shot ledger is never rewritten.
        with closing(open_production(self.production_db_path)) as db:
            prepare_schema(db)
            prepare_characters(db)
            prepare_character_v2(db)
            prepare_shot_character(db)
            prepare_scenes(db)
            prepare_workflows(db)
            prepare_video_results(db)
            prepare_picture_cuts(db)
            prepare_picture_cut_jobs(db)
            prepare_audio_stems(db)
            prepare_av_masters(db)
            prepare_av_master_jobs(db)
            prepare_subtitle_tracks(db)
            prepare_release_candidates(db)
            prepare_release_jobs(db)
        super().__init__(bind, StudioHandler)

    def stop(self):
        self.is_running = False
        self.poller.running = False
        self.shutdown()


class StudioHandler(BaseHTTPRequestHandler):
    server_version = "DirectorStudio/0.8"
    sys_version = ""

    def log_message(self, *args):
        # Do not persist user note contents, query strings or private auth data.
        return

    def headers_safe(self):
        host = self.headers.get("Host", "")
        return host in HOSTS and self.client_address[0] == "127.0.0.1"

    def microsoft_proxy(self):
        # Protect the public proxy even during the short period between the
        # systemd SSO activation and Nginx route promotion. Missing a marker
        # must NEVER downgrade configured Microsoft owner authentication.
        required = os.environ.get("DIRECTOR_STUDIO_MICROSOFT_REQUIRED") == "1"
        marked = self.headers.get("X-Director-Studio-Auth-Mode") == "microsoft"
        return ((required or marked)
                and self.headers.get("X-Forwarded-Proto") == "https"
                and self.headers.get("X-Forwarded-Host") == "jipite.borealos.cn")

    def public_mode_mismatch(self):
        required = os.environ.get("DIRECTOR_STUDIO_MICROSOFT_REQUIRED") == "1"
        public_host = self.headers.get("X-Forwarded-Host") == "jipite.borealos.cn"
        marked = self.headers.get("X-Director-Studio-Auth-Mode") == "microsoft"
        return (marked or (required and public_host)) and not self.microsoft_proxy()

    def authenticated(self):
        if self.server.identity is None:
            return None
        sid = cookies(self.headers.get("Cookie","")).get(COOKIE_SID)
        return self.server.identity.check(sid)

    def redirect(self, url, *, set_cookies=()):
        self.send_response(302)
        self.common_headers("text/plain; charset=utf-8")
        self.send_header("Location", url)
        for cookie in set_cookies:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def common_headers(self, mime):
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)

    def reply(self, code, value):
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.common_headers("application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def file(self, filename, mime):
        path = BASE / filename
        raw = path.read_bytes()
        self.send_response(200)
        self.common_headers(mime)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def fresh_snapshot(self):
        with closing(connect(self.server.db_path)) as db:
            value = snapshot(db)
        value["live"] = self.server.poller.current()
        value["production"] = dashboard_from_path(self.server.production_db_path)
        value["sample_age_seconds"] = (
            max(0, int(time.time()) - value["live"]["last_checked"])
            if value["live"]["last_checked"] is not None else None)
        return value

    def stream_private_mp4(self, filename, size):
        return self.stream_private_media(filename,size,"video/mp4")

    def stream_private_wav(self, filename, size):
        return self.stream_private_media(filename,size,"audio/wav")

    def stream_private_media(self, filename, size, mime):
        # Stream only from a validated owner-scoped immutable file path.
        # One exact HTTP Range only; video player seeking must not
        # trigger a 250MB in-memory response.
        header=self.headers.get("Range")
        start,end=0,size-1
        if header:
            import re
            match=re.fullmatch(r"bytes=(\d+)-(\d*)",header)
            if not match:
                return self.reply(416,{"ok":False,"reason":"invalid_video_range"})
            start=int(match.group(1))
            if match.group(2):end=int(match.group(2))
            if start>=size or end<start or end>=size:
                return self.reply(416,{"ok":False,"reason":"invalid_video_range"})
        fd=os.open(filename,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            import stat
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size!=size:
                raise VideoResultError("video_take_storage_mismatch",503)
            self.send_response(206 if header else 200)
            self.common_headers(mime)
            self.send_header("Accept-Ranges","bytes")
            self.send_header("Content-Length",str(end-start+1))
            if header:
                self.send_header("Content-Range",f"bytes {start}-{end}/{size}")
            self.end_headers()
            with os.fdopen(fd,"rb") as media:
                fd=None
                media.seek(start)
                left=end-start+1
                while left:
                    chunk=media.read(min(left,1<<20))
                    if not chunk:break
                    self.wfile.write(chunk)
                    left-=len(chunk)
        finally:
            if fd is not None:os.close(fd)
        return

    def do_GET(self):
        if not self.headers_safe():
            return self.reply(403, {"ok": False, "reason": "invalid_host"})
        if self.public_mode_mismatch():
            return self.reply(403, {"ok":False,"reason":"proxy_auth_mode_invalid"})
        url = urlsplit(self.path)
        path = url.path
        secured = self.microsoft_proxy()
        if secured:
            if self.server.identity is None:
                return self.reply(503, {"ok":False,"reason":"microsoft_login_not_configured"})
            if path == "/auth/start":
                try:
                    auth_uri, state = self.server.identity.start()
                    return self.redirect(auth_uri, set_cookies=(state_cookie(state),))
                except Exception:
                    return self.reply(503, {"ok":False,"reason":"microsoft_login_unavailable"})
            if path == "/auth/callback":
                try:
                    # Recognize malformed/extra parameters as invalid_callback
                    # so the bounded parameter-name-only diagnostic can explain
                    # the rejection without storing any auth code or token.
                    if len(url.query) > 16384:
                        raise IdentityError("invalid_callback")
                    try:
                        pairs=parse_qsl(url.query, keep_blank_values=True, max_num_fields=32)
                    except (ValueError, UnicodeError):
                        raise IdentityError("invalid_callback") from None
                    names=[key for key,_ in pairs]
                    if (not 2 <= len(pairs) <= len(ALLOWED_CALLBACK_FIELDS)
                            or len(set(names)) != len(names)
                            or not {"state","code"}.issubset(names)
                            or set(names) - ALLOWED_CALLBACK_FIELDS):
                        raise IdentityError("invalid_callback")
                    query=dict(pairs)
                    state=cookies(self.headers.get("Cookie","")).get(COOKIE_STATE)
                    sid=self.server.identity.finish(query,state)
                    return self.redirect("/studio/",set_cookies=(
                        session_cookie(sid),clear_cookie(COOKIE_STATE)))
                except IdentityError as exc:
                    # Log ONLY a fixed, non-sensitive reason. Never log the
                    # callback URL, authorization code, cookie or ID token.
                    reasons = {
                        "invalid_callback", "oidc_state_invalid",
                        "oidc_flow_expired", "microsoft_token_exchange_failed",
                        "microsoft_token_verification_failed",
                        "microsoft_owner_not_authorized", "too_many_sessions",
                    }
                    reason = str(exc) if str(exc) in reasons else "oidc_internal_error"
                    diagnostics = (" "+callback_fields_for_log(url.query)
                                   if reason == "invalid_callback" else "")
                    if reason in ("microsoft_token_exchange_failed",
                                  "microsoft_token_verification_failed"):
                        # IdentityError.diagnostic comes only from the fixed,
                        # vetted exception class allowlist, never from a
                        # potentially secret-bearing exception message.
                        cls = getattr(exc, "diagnostic", None)
                        if cls:
                            diagnostics += " exc_class=" + cls
                    print("STUDIO_AUTH_CALLBACK_DENIED "+reason+diagnostics, flush=True)
                    return self.reply(403, {"ok":False,"reason":"microsoft_login_failed"})
                except Exception:
                    print("STUDIO_AUTH_CALLBACK_DENIED oidc_internal_error", flush=True)
                    return self.reply(403, {"ok":False,"reason":"microsoft_login_failed"})
            session=self.authenticated()
            if path == "/auth/status":
                return self.reply(200,{"authenticated":bool(session),
                                      "mode":"microsoft_personal_owner"})
            # The login page belongs to Director Studio, not the identity
            # provider. It is intentionally public but contains zero production
            # data and NO session tokens, project names or private APIs.
            if session is None:
                if path in ("/", "/login"):
                    return self.file("login.html", "text/html; charset=utf-8")
                if path == "/login.css":
                    return self.file("login.css", "text/css; charset=utf-8")
                return self.reply(401,{"ok":False,"reason":"microsoft_login_required"})
            if path == "/login":
                return self.redirect("/studio/")
            if path == "/login.css":
                return self.file("login.css", "text/css; charset=utf-8")
        if path == "/":
            return self.file("index.html", "text/html; charset=utf-8")
        if path == "/studio.css":
            return self.file("studio.css", "text/css; charset=utf-8")
        if path == "/studio.js":
            return self.file("studio.js", "application/javascript; charset=utf-8")
        if path in ("/glacier-peaks.svg", "/glacier-banner.svg"):
            return self.file(path.lstrip("/"), "image/svg+xml; charset=utf-8")
        if path == "/api/v1/bootstrap":
            csrf = session["csrf"] if secured else self.server.csrf_token
            return self.reply(200, {"ok": True, "csrf": csrf,
                                    "mode": "microsoft_owner" if secured else
                                    "ssh_only_local_supervisor"})
        if path == "/api/v1/snapshot":
            return self.reply(200, self.fresh_snapshot())
        if path == "/api/v1/production":
            return self.reply(200, dashboard_from_path(self.server.production_db_path))
        if path == "/api/v1/production/episode":
            # Episode details include private media-version metadata: allow
            # only the signed-in Microsoft owner, not SSH/basic/anonymous.
            if not secured:
                return self.reply(403, {"ok":False,"reason":"microsoft_owner_required"})
            try:
                pairs=parse_qsl(url.query, keep_blank_values=True, max_num_fields=4)
                if (len(pairs) != 2 or len(set(k for k,_ in pairs))!=2
                        or set(k for k,_ in pairs)!={"project","episode"}):
                    raise ProductionError("invalid_episode_query")
                args=dict(pairs)
                detail=episode_detail_from_path(
                    self.server.production_db_path,args["project"],args["episode"])
                return self.reply(200,detail)
            except ProductionError as exc:
                return self.reply(404 if str(exc)=="episode_not_found" else 400,
                                  {"ok":False,"reason":str(exc)})
            except (ValueError,UnicodeError):
                return self.reply(400,{"ok":False,"reason":"invalid_episode_query"})
            except Exception:
                return self.reply(503,{"ok":False,"reason":"production_storage_unavailable"})
        if path == "/api/v1/workflow":
            if not secured:
                return self.reply(403,{"ok":False,"reason":"microsoft_owner_required"})
            try:
                pairs=parse_qsl(url.query,keep_blank_values=True,max_num_fields=4)
                if len(pairs) not in (2,3) or len({k for k,v in pairs})!=len(pairs):
                    raise WorkflowError("invalid_workflow_query")
                args=dict(pairs)
                if set(args) not in ({"project","kind"},{"project","kind","episode"}):
                    raise WorkflowError("invalid_workflow_query")
                return self.reply(200,list_workflow_units(
                    self.server.production_db_path,args["project"],
                    args["kind"],args.get("episode","")))
            except WorkflowError as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (sqlite3.Error,OSError,ProductionError,ValueError):
                return self.reply(503,{"ok":False,"reason":"workflow_storage_unavailable"})
        if path in ("/api/v1/release","/api/v1/release/readiness",
                    "/api/v1/release/file","/api/v1/release/jobs",
                    "/api/v1/release/receipt"):
            if not secured:
                return self.reply(403,{"ok":False,"reason":"microsoft_owner_required"})
            try:
                fields={"project","episode"}
                if path.endswith("/file") or path.endswith("/receipt"):
                    fields.add("release")
                pairs=parse_qsl(url.query,keep_blank_values=True,max_num_fields=4)
                if len(pairs)!=len(fields) or len({k for k,v in pairs})!=len(pairs) or (
                    set(dict(pairs))!=fields):
                    raise ReleaseError("invalid_release_query")
                args=dict(pairs)
                if path.endswith("/receipt"):
                    return self.reply(200,get_private_delivery_receipt(
                        self.server.production_db_path,args["project"],
                        args["episode"],args["release"]))
                if path.endswith("/readiness"):
                    return self.reply(200,get_release_readiness(
                        self.server.production_db_path,args["project"],args["episode"]))
                if path.endswith("/jobs"):
                    return self.reply(200,list_release_jobs(
                        self.server.production_db_path,args["project"],args["episode"]))
                if not path.endswith("/file"):
                    return self.reply(200,list_release_candidates(
                        self.server.production_db_path,args["project"],args["episode"]))
                file,size=get_release_file(
                    self.server.production_db_path,args["project"],
                    args["episode"],args["release"])
                return self.stream_private_mp4(file,size)
            except (ReleaseError,ReleaseJobError,VideoResultError) as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (sqlite3.Error,OSError,ProductionError):
                return self.reply(503,{"ok":False,"reason":"release_storage_unavailable"})
        if path in ("/api/v1/subtitles","/api/v1/subtitles/file",
                    "/api/v1/subtitles/vtt"):
            if not secured:
                return self.reply(403,{"ok":False,"reason":"microsoft_owner_required"})
            try:
                fields={"project","episode"}
                if path.endswith("/file") or path.endswith("/vtt"):
                    fields.add("subtitle")
                pairs=parse_qsl(url.query,keep_blank_values=True,max_num_fields=4)
                if len(pairs)!=len(fields) or len({k for k,v in pairs})!=len(pairs) or (
                    set(dict(pairs))!=fields):
                    raise SubtitleError("invalid_subtitle_query")
                args=dict(pairs)
                if not path.endswith("/file") and not path.endswith("/vtt"):
                    return self.reply(200,list_subtitle_tracks(
                        self.server.production_db_path,args["project"],args["episode"]))
                path_to_text=get_subtitle_file(self.server.production_db_path,
                    args["project"],args["episode"],args["subtitle"])
                text=path_to_text.read_text(encoding="utf-8")
                if path.endswith("/vtt"):
                    content=as_webvtt(text).encode("utf-8")
                    self.send_response(200)
                    self.common_headers("text/vtt; charset=utf-8")
                    self.send_header("Content-Length",str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                    return
                return self.reply(200,{"ok":True,
                    "subtitle_id":args["subtitle"],"text":text,
                    "gpu_action":False})
            except SubtitleError as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (sqlite3.Error,OSError,UnicodeError):
                return self.reply(503,{"ok":False,"reason":"subtitle_storage_unavailable"})
        if path in ("/api/v1/av-master","/api/v1/av-master/readiness",
                    "/api/v1/av-master/file","/api/v1/av-master/jobs"):
            if not secured:
                return self.reply(403,{"ok":False,"reason":"microsoft_owner_required"})
            try:
                required={"project","episode"}
                if path.endswith("/file"):required.add("master")
                pairs=parse_qsl(url.query,keep_blank_values=True,max_num_fields=4)
                if len(pairs)!=len(required) or len({k for k,v in pairs})!=len(pairs) or (
                    set(dict(pairs))!=required):
                    raise MasterError("invalid_master_query")
                args=dict(pairs)
                if path.endswith("/readiness"):
                    return self.reply(200,get_av_master_readiness(
                        self.server.production_db_path,args["project"],args["episode"]))
                if path.endswith("/jobs"):
                    return self.reply(200,list_av_master_jobs(
                        self.server.production_db_path,args["project"],args["episode"]))
                if not path.endswith("/file"):
                    return self.reply(200,list_av_masters(
                        self.server.production_db_path,args["project"],args["episode"]))
                filename,size=get_av_master_file(
                    self.server.production_db_path,args["project"],
                    args["episode"],args["master"])
                return self.stream_private_mp4(filename,size)
            except (MasterError,MasterJobError,VideoResultError) as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (sqlite3.Error,OSError,ProductionError):
                return self.reply(503,{"ok":False,"reason":"master_storage_unavailable"})
        if path in ("/api/v1/audio-stems","/api/v1/audio-stems/file"):
            if not secured:
                return self.reply(403,{"ok":False,"reason":"microsoft_owner_required"})
            try:
                required={"project","episode"}
                if path.endswith("/file"):required.add("audio")
                pairs=parse_qsl(url.query,keep_blank_values=True,max_num_fields=4)
                if len(pairs)!=len(required) or len({k for k,v in pairs})!=len(pairs) or (
                    set(dict(pairs))!=required):
                    raise AudioError("invalid_audio_query")
                args=dict(pairs)
                if not path.endswith("/file"):
                    return self.reply(200,list_audio_stems(
                        self.server.production_db_path,args["project"],args["episode"]))
                filename,size=get_audio_stem_file(
                    self.server.production_db_path,args["project"],
                    args["episode"],args["audio"])
                return self.stream_private_wav(filename,size)
            except (AudioError,VideoResultError) as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (sqlite3.Error,OSError,ProductionError):
                return self.reply(503,{"ok":False,"reason":"audio_storage_unavailable"})
        if path in ("/api/v1/picture-cuts/readiness","/api/v1/picture-cuts",
                    "/api/v1/picture-cuts/file","/api/v1/picture-cuts/jobs"):
            if not secured:
                return self.reply(403,{"ok":False,"reason":"microsoft_owner_required"})
            try:
                required={"project","episode"}
                if path.endswith("/file"):required.add("cut")
                pairs=parse_qsl(url.query,keep_blank_values=True,max_num_fields=4)
                if len(pairs)!=len(required) or len({k for k,v in pairs})!=len(pairs) or (
                    set(dict(pairs))!=required):
                    raise PictureCutError("invalid_picture_cut_query")
                args=dict(pairs)
                if path.endswith("/jobs"):
                    return self.reply(200,list_picture_cut_jobs(
                        self.server.production_db_path,args["project"],args["episode"]))
                if path.endswith("/readiness"):
                    return self.reply(200,get_picture_cut_readiness(
                        self.server.production_db_path,args["project"],args["episode"]))
                if not path.endswith("/file"):
                    return self.reply(200,list_picture_cuts(
                        self.server.production_db_path,args["project"],args["episode"]))
                filename,size=get_picture_cut_file(
                    self.server.production_db_path,args["project"],
                    args["episode"],args["cut"])
                return self.stream_private_mp4(filename,size)
            except (PictureCutError,PictureJobError,VideoResultError) as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (OSError,sqlite3.Error,ProductionError):
                return self.reply(503,{"ok":False,"reason":"picture_cut_storage_unavailable"})
        if path in ("/api/v1/video-results","/api/v1/video-results/file"):
            if not secured:
                return self.reply(403,{"ok":False,"reason":"microsoft_owner_required"})
            try:
                fields={"project","episode","shot"}
                if path.endswith("/file"):
                    fields.add("take")
                pairs=parse_qsl(url.query,keep_blank_values=True,max_num_fields=5)
                if len(pairs)!=len(fields) or len({k for k,v in pairs})!=len(pairs) or (
                    set(dict(pairs))!=fields):
                    raise VideoResultError("invalid_video_result_query")
                args=dict(pairs)
                if not path.endswith("/file"):
                    return self.reply(200,list_video_takes(
                        self.server.production_db_path,args["project"],
                        args["episode"],args["shot"]))
                filename,size=get_video_take_file(
                    self.server.production_db_path,args["project"],
                    args["episode"],args["shot"],args["take"])
                return self.stream_private_mp4(filename,size)
            except VideoResultError as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (OSError,sqlite3.Error,ProductionError):
                return self.reply(503,{"ok":False,"reason":"video_storage_unavailable"})
        if path == "/api/v1/workflow/video-packages":
            if not secured:
                return self.reply(403,{"ok":False,"reason":"microsoft_owner_required"})
            try:
                pairs=parse_qsl(url.query,keep_blank_values=True,max_num_fields=3)
                if len(pairs)!=2 or len({k for k,v in pairs})!=2 or (
                    set(dict(pairs))!={"project","episode"}):
                    raise WorkflowError("invalid_workflow_query")
                args=dict(pairs)
                return self.reply(200,get_workflow_episode_handoffs(
                    self.server.production_db_path,args["project"],args["episode"]))
            except WorkflowError as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (sqlite3.Error,OSError,ProductionError,ValueError):
                return self.reply(503,{"ok":False,"reason":"workflow_storage_unavailable"})
        if path == "/api/v1/workflow/video-package":
            if not secured:
                return self.reply(403,{"ok":False,"reason":"microsoft_owner_required"})
            try:
                pairs=parse_qsl(url.query,keep_blank_values=True,max_num_fields=4)
                if (len(pairs)!=3 or len({k for k,v in pairs})!=3 or
                    set(dict(pairs))!={"project","episode","shot"}):
                    raise WorkflowError("invalid_workflow_query")
                args=dict(pairs)
                return self.reply(200,get_workflow_handoff(
                    self.server.production_db_path,args["project"],
                    args["episode"],args["shot"]))
            except WorkflowError as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (sqlite3.Error,OSError,ProductionError,ValueError):
                return self.reply(503,{"ok":False,"reason":"workflow_storage_unavailable"})
        if path == "/api/v1/workflow/readiness":
            if not secured:
                return self.reply(403,{"ok":False,"reason":"microsoft_owner_required"})
            try:
                pairs=parse_qsl(url.query,keep_blank_values=True,max_num_fields=3)
                if (len(pairs)!=2 or len({k for k,v in pairs})!=2 or
                    set(dict(pairs))!={"project","episode"}):
                    raise WorkflowError("invalid_workflow_query")
                args=dict(pairs)
                return self.reply(200,get_workflow_readiness(
                    self.server.production_db_path,args["project"],args["episode"]))
            except WorkflowError as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (sqlite3.Error,OSError,ProductionError,ValueError):
                return self.reply(503,{"ok":False,"reason":"workflow_storage_unavailable"})
        if path == "/api/v1/workflow/reviews":
            if not secured:
                return self.reply(403,{"ok":False,"reason":"microsoft_owner_required"})
            try:
                pairs=parse_qsl(url.query,keep_blank_values=True,max_num_fields=3)
                args=dict(pairs)
                if len(pairs) not in (1,2) or len({k for k,v in pairs})!=len(pairs) or (
                    set(args) not in ({"project"},{"project","episode"})):
                    raise WorkflowError("invalid_workflow_query")
                return self.reply(200,list_workflow_reviews(
                    self.server.production_db_path,args["project"],
                    args.get("episode","")))
            except WorkflowError as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (sqlite3.Error,OSError,ProductionError):
                return self.reply(503,{"ok":False,"reason":"workflow_storage_unavailable"})
        if path == "/api/v1/scenes":
            if not secured:
                return self.reply(403,{"ok":False,"reason":"microsoft_owner_required"})
            try:
                pairs=parse_qsl(url.query,keep_blank_values=True,max_num_fields=2)
                if len(pairs)!=1 or pairs[0][0]!="project":
                    raise SceneError("invalid_scene_query")
                return self.reply(200,list_scenes(
                    self.server.production_db_path,pairs[0][1]))
            except SceneError as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (sqlite3.Error,OSError,ProductionError):
                return self.reply(503,{"ok":False,"reason":"scene_storage_unavailable"})
        if path == "/api/v1/characters/shot-bindings":
            if not secured:
                return self.reply(403, {"ok":False,"reason":"microsoft_owner_required"})
            try:
                pairs=parse_qsl(url.query,keep_blank_values=True,max_num_fields=3)
                if len(pairs)!=2 or len({k for k,v in pairs})!=2 or {
                        k for k,v in pairs}!={"project","episode"}:
                    raise CharacterError("invalid_shot_binding_query")
                args=dict(pairs)
                return self.reply(200,list_shot_character(
                    self.server.production_db_path,args["project"],args["episode"]))
            except CharacterError as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (sqlite3.Error,OSError,ProductionError):
                return self.reply(503,{"ok":False,"reason":"shot_binding_storage_unavailable"})
        if path == "/api/v1/characters/assets":
            if not secured:
                return self.reply(403, {"ok":False,"reason":"microsoft_owner_required"})
            try:
                pairs=parse_qsl(url.query,keep_blank_values=True,max_num_fields=3)
                if len(pairs)!=2 or {k for k,v in pairs}!={"project","character"}:
                    raise CharacterError("invalid_v2_asset_query")
                args=dict(pairs)
                return self.reply(200,list_character_v2(
                    self.server.production_db_path,args["project"],args["character"]))
            except CharacterError as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (sqlite3.Error,OSError,ProductionError):
                return self.reply(503,{"ok":False,"reason":"character_storage_unavailable"})
        if path == "/api/v1/characters":
            if not secured:
                return self.reply(403, {"ok":False,"reason":"microsoft_owner_required"})
            try:
                pairs=parse_qsl(url.query,keep_blank_values=True,max_num_fields=2)
                if len(pairs)!=1 or pairs[0][0]!="project":
                    raise CharacterError("invalid_character_query")
                return self.reply(200,list_characters(
                    self.server.production_db_path,pairs[0][1]))
            except CharacterError as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (sqlite3.Error,OSError):
                return self.reply(503,{"ok":False,"reason":"character_storage_unavailable"})
        if path in ("/api/v1/production/visuals", "/api/v1/production/visual"):
            if not secured:
                return self.reply(403, {"ok":False,"reason":"microsoft_owner_required"})
            try:
                fields = {"project","episode"} if path.endswith("/visuals") else {"project","episode","id"}
                pairs = parse_qsl(url.query,keep_blank_values=True,max_num_fields=4)
                if len(pairs)!=len(fields) or set(k for k,_ in pairs)!=fields:
                    raise VisualError("invalid_visual_query")
                query = dict(pairs)
                if path.endswith("/visuals"):
                    return self.reply(200,list_visuals(self.server.production_db_path,
                                                       query["project"],query["episode"]))
                mime,payload=read_visual(self.server.production_db_path,
                    query["project"],query["episode"],query["id"])
                self.send_response(200)
                self.common_headers(mime)
                self.send_header("Content-Length",str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            except (VisualError,ProductionError) as exc:
                return self.reply(getattr(exc,"status",400),
                                  {"ok":False,"reason":str(exc)})
            except (OSError,sqlite3.Error):
                return self.reply(503,{"ok":False,"reason":"visual_storage_unavailable"})
        if path != "/api/v1/stream":
            return self.reply(404, {"ok": False, "reason": "not_found"})
        self.send_response(200)
        self.common_headers("text/event-stream; charset=utf-8")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            sid = cookies(self.headers.get("Cookie","")).get(COOKIE_SID) if secured else None
            while self.server.is_running:
                if secured and self.server.identity.check(sid) is None:
                    break
                data = json.dumps(self.fresh_snapshot(), ensure_ascii=False,
                                  separators=(",", ":"))
                self.wfile.write(("event: snapshot\ndata: " + data + "\n\n").encode("utf-8"))
                self.wfile.flush()
                time.sleep(2)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def handle_brain_visual_post(self):
        """Signed localhost-only upload; never reachable from a browser session."""
        target="/api/v1/brain/visual"
        auth=self.server.brain_auth
        if auth.secret is None:
            return self.reply(503,{"ok":False,"reason":"brain_link_not_configured"})
        if self.path!=target:
            return self.reply(403,{"ok":False,"reason":"brain_link_denied"})
        if self.headers.get("Content-Type","").split(";")[0].strip()!="application/json":
            return self.reply(415,{"ok":False,"reason":"json_only"})
        if self.headers.get("Transfer-Encoding") is not None:
            return self.reply(400,{"ok":False,"reason":"unsupported_request_encoding"})
        raw_len=self.headers.get("Content-Length","")
        if not raw_len.isascii() or not raw_len.isdigit() or len(raw_len)>9:
            return self.reply(400,{"ok":False,"reason":"invalid_content_length"})
        length=int(raw_len)
        if length<2 or length>MAX_POST_BYTES:
            return self.reply(413,{"ok":False,"reason":"invalid_request_size"})
        raw=self.rfile.read(length)
        if len(raw)!=length:
            return self.reply(400,{"ok":False,"reason":"incomplete_request"})
        if not auth.check(self.headers,"POST",target,raw,self.client_address[0]):
            return self.reply(403,{"ok":False,"reason":"brain_link_denied"})
        try:
            data=json.loads(raw)
            output=ingest_chatgpt_image(self.server.production_db_path,data,
                                        actor="trusted_chatgpt_file_bridge")
            return self.reply(200 if output["unchanged"] else 201,output)
        except VisualError as exc:
            return self.reply(exc.status,{"ok":False,"reason":exc.reason})
        except (TypeError,ValueError,UnicodeError):
            return self.reply(400,{"ok":False,"reason":"invalid_visual_payload"})
        except (OSError,sqlite3.Error,ProductionError):
            return self.reply(503,{"ok":False,"reason":"visual_storage_unavailable"})

    def handle_brain_post(self):
        # This route must never accept a public reverse-proxy request, browser
        # cookies, Origin or arbitrary upstream forwarding headers.
        auth=self.server.brain_auth
        if auth.secret is None:
            return self.reply(503,{"ok":False,"reason":"brain_link_not_configured"})
        if self.path != BRAIN_PATH:
            return self.reply(403,{"ok":False,"reason":"brain_link_denied"})
        if self.headers.get("Content-Type","").split(";")[0].strip()!="application/json":
            return self.reply(415,{"ok":False,"reason":"json_only"})
        if self.headers.get("Transfer-Encoding") is not None:
            return self.reply(400,{"ok":False,"reason":"unsupported_request_encoding"})
        raw_length=self.headers.get("Content-Length","")
        if not raw_length.isascii() or not raw_length.isdigit() or len(raw_length)>8:
            return self.reply(400,{"ok":False,"reason":"invalid_content_length"})
        length=int(raw_length)
        if length<2 or length>MAX_BRAIN_BODY:
            return self.reply(413,{"ok":False,"reason":"brain_request_too_large"})
        body=self.rfile.read(length)
        if len(body)!=length:
            return self.reply(400,{"ok":False,"reason":"incomplete_request"})
        if not auth.check(self.headers,"POST",BRAIN_PATH,body,self.client_address[0]):
            return self.reply(403,{"ok":False,"reason":"brain_link_denied"})
        try:
            data=json.loads(body)
            if not isinstance(data,dict) or set(data)!={"tool","arguments"}:
                raise BrainError("invalid_brain_request")
            result=execute_brain(self.server.production_db_path,
                                 data["tool"],data["arguments"])
            return self.reply(200,result)
        except BrainError as exc:
            return self.reply(exc.status,{"ok":False,"reason":exc.reason})
        except (ValueError,TypeError,UnicodeError):
            return self.reply(400,{"ok":False,"reason":"invalid_brain_request"})
        except Exception:
            # Do not emit private creative text or database content in logs.
            return self.reply(503,{"ok":False,"reason":"studio_brain_unavailable"})

    def do_POST(self):
        if not self.headers_safe():
            return self.reply(403, {"ok": False, "reason": "invalid_host"})
        if urlsplit(self.path).path==BRAIN_PATH:
            return self.handle_brain_post()
        if urlsplit(self.path).path=="/api/v1/brain/visual":
            return self.handle_brain_visual_post()
        if self.public_mode_mismatch():
            return self.reply(403, {"ok": False, "reason": "invalid_host"})
        path = urlsplit(self.path).path
        secured = self.microsoft_proxy()
        if secured:
            if self.server.identity is None:
                return self.reply(503, {"ok":False,"reason":"microsoft_login_not_configured"})
            session=self.authenticated()
            if session is None:
                return self.reply(401,{"ok":False,"reason":"microsoft_login_required"})
        if path not in ("/api/v1/action", "/auth/logout",
                        "/api/v1/production/action",
                        "/api/v1/production/visual/upload",
                        "/api/v1/production/visual/select",
                        "/api/v1/characters/create",
                        "/api/v1/characters/update",
                        "/api/v1/characters/link",
                        "/api/v1/characters/approve",
                        "/api/v1/characters/assets/create",
                        "/api/v1/characters/assets/revise",
                        "/api/v1/characters/assets/review",
                        "/api/v1/characters/shot-bindings/save",
                        "/api/v1/scenes/create",
                        "/api/v1/scenes/update",
                        "/api/v1/scenes/link",
                        "/api/v1/scenes/review",
                        "/api/v1/workflow/save",
                        "/api/v1/workflow/review",
                        "/api/v1/video-results/start",
                        "/api/v1/video-results/chunk",
                        "/api/v1/video-results/finish",
                        "/api/v1/video-results/review",
                        "/api/v1/picture-cuts/review",
                        "/api/v1/picture-cuts/assemble",
                        "/api/v1/audio-stems/start",
                        "/api/v1/audio-stems/chunk",
                        "/api/v1/audio-stems/finish",
                        "/api/v1/audio-stems/review",
                        "/api/v1/av-master/assemble",
                        "/api/v1/av-master/review",
                        "/api/v1/subtitles/save",
                        "/api/v1/subtitles/review",
                        "/api/v1/release/assemble",
                        "/api/v1/release/review"):
            return self.reply(404, {"ok": False, "reason": "not_found"})
        if (path.startswith("/api/v1/production/") or
                path.startswith("/api/v1/characters/") or
                path.startswith("/api/v1/scenes/") or
                path.startswith("/api/v1/workflow/") or
                path.startswith("/api/v1/video-results/") or
                path.startswith("/api/v1/picture-cuts/") or
                path.startswith("/api/v1/audio-stems/") or
                path.startswith("/api/v1/av-master/") or
                path.startswith("/api/v1/subtitles/") or
                path.startswith("/api/v1/release/")) and not secured:
            return self.reply(403, {"ok":False,"reason":"microsoft_owner_required"})
        if path=="/auth/logout" and not secured:
            return self.reply(404, {"ok": False, "reason": "not_found"})
        origin = self.headers.get("Origin", "")
        via_tls_proxy = (
            self.headers.get("X-Forwarded-Proto") == "https"
            and self.headers.get("X-Forwarded-Host") == "jipite.borealos.cn"
        )
        permitted = ("https://jipite.borealos.cn",) if via_tls_proxy else (
            "http://127.0.0.1:8900", "http://localhost:8900"
        )
        if origin not in permitted:
            return self.reply(403, {"ok": False, "reason": "invalid_origin"})
        if path == "/auth/logout":
            if not secrets.compare_digest(
                    self.headers.get("X-CSRF-Token",""), session["csrf"]):
                return self.reply(403,{"ok":False,"reason":"csrf_denied"})
            sid=cookies(self.headers.get("Cookie","")).get(COOKIE_SID)
            self.server.identity.logout(sid)
            self.send_response(204)
            self.common_headers("application/json; charset=utf-8")
            self.send_header("Set-Cookie", clear_cookie(COOKIE_SID))
            self.send_header("Content-Length","0")
            self.end_headers()
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self.reply(415, {"ok": False, "reason": "json_only"})
        raw_len=self.headers.get("Content-Length","")
        if (self.headers.get("Transfer-Encoding") is not None
                or not raw_len.isascii() or not raw_len.isdigit() or len(raw_len)>9):
            return self.reply(400,{"ok":False,"reason":"invalid_content_length"})
        length=int(raw_len)
        max_allowed=(MAX_POST_BYTES if path.endswith("/visual/upload") else
                     VIDEO_CHUNK_BYTES*4//3+4096 if path in (
                         "/api/v1/video-results/chunk","/api/v1/audio-stems/chunk")
                     else 400000 if path=="/api/v1/subtitles/save"
                     else MAX_BODY)
        if not 1 <= length <= max_allowed:
            return self.reply(413, {"ok": False, "reason": "invalid_request_size"})
        try:
            data = json.loads(self.rfile.read(length))
            if not isinstance(data,dict):
                raise ValueError
            if (path=="/api/v1/action" and
                    set(data) - {"csrf", "action", "shot_id", "revision", "reason"}):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            return self.reply(400, {"ok": False, "reason": "invalid_json"})
        expected_csrf=session["csrf"] if secured else self.server.csrf_token
        if not secrets.compare_digest(str(data.get("csrf", "")), expected_csrf):
            return self.reply(403, {"ok": False, "reason": "csrf_denied"})
        if path in ("/api/v1/release/assemble","/api/v1/release/review"):
            try:
                actor=operator_from_verified_session(session)
                fields={k:v for k,v in data.items() if k!="csrf"}
                if path.endswith("/assemble"):
                    result=enqueue_release_job(
                        self.server.production_db_path,fields,actor)
                    return self.reply(202,result)
                result=review_release_candidate(
                    self.server.production_db_path,fields,actor)
                return self.reply(200,result)
            except (ReleaseError,ReleaseJobError) as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (ProductionWebError,ProductionError,ValueError,TypeError):
                return self.reply(400,{"ok":False,"reason":"invalid_release_request"})
            except (sqlite3.Error,OSError):
                return self.reply(503,{"ok":False,"reason":"release_storage_unavailable"})
        if path in ("/api/v1/subtitles/save","/api/v1/subtitles/review"):
            try:
                actor=operator_from_verified_session(session)
                fields={k:v for k,v in data.items() if k!="csrf"}
                action=save_subtitle_track if path.endswith("/save") else review_subtitle_track
                return self.reply(200,action(
                    self.server.production_db_path,fields,actor))
            except SubtitleError as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (ProductionWebError,ProductionError,ValueError,TypeError):
                return self.reply(400,{"ok":False,"reason":"invalid_subtitle_request"})
            except (sqlite3.Error,OSError):
                return self.reply(503,{"ok":False,"reason":"subtitle_storage_unavailable"})
        if path in ("/api/v1/av-master/assemble","/api/v1/av-master/review"):
            try:
                actor=operator_from_verified_session(session)
                fields={k:v for k,v in data.items() if k!="csrf"}
                if path.endswith("/assemble"):
                    result=enqueue_av_master(
                        self.server.production_db_path,fields,actor)
                    return self.reply(202,result)
                result=review_av_master(
                    self.server.production_db_path,fields,actor)
                return self.reply(200,result)
            except (MasterError,MasterJobError) as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (ProductionWebError,ProductionError,ValueError,TypeError):
                return self.reply(400,{"ok":False,"reason":"invalid_master_request"})
            except (sqlite3.Error,OSError):
                return self.reply(503,{"ok":False,"reason":"master_storage_unavailable"})
        if path.startswith("/api/v1/audio-stems/"):
            try:
                actor=operator_from_verified_session(session)
                fields={k:v for k,v in data.items() if k!="csrf"}
                if path=="/api/v1/audio-stems/start":
                    with self.server.audio_upload_lock:
                        result=begin_audio_upload(
                            self.server.production_db_path,fields,actor)
                elif path=="/api/v1/audio-stems/chunk":
                    result=append_audio_chunk(
                        self.server.production_db_path,fields,actor,
                        self.server.audio_upload_lock)
                elif path=="/api/v1/audio-stems/finish":
                    result=finish_audio_upload(
                        self.server.production_db_path,fields,actor,
                        self.server.audio_upload_lock)
                else:
                    result=review_audio_stem(
                        self.server.production_db_path,fields,actor)
                return self.reply(200,result)
            except AudioError as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (ProductionWebError,ProductionError,ValueError,TypeError):
                return self.reply(400,{"ok":False,"reason":"invalid_audio_request"})
            except (sqlite3.Error,OSError):
                return self.reply(503,{"ok":False,"reason":"audio_storage_unavailable"})
        if path=="/api/v1/picture-cuts/assemble":
            try:
                actor=operator_from_verified_session(session)
                fields={k:v for k,v in data.items() if k!="csrf"}
                return self.reply(202,enqueue_picture_cut(
                    self.server.production_db_path,fields,actor))
            except PictureJobError as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (ProductionWebError,ProductionError,ValueError):
                return self.reply(400,{"ok":False,"reason":"invalid_picture_cut_job"})
            except (sqlite3.Error,OSError):
                return self.reply(503,{"ok":False,"reason":"picture_cut_job_storage_unavailable"})
        if path=="/api/v1/picture-cuts/review":
            try:
                actor=operator_from_verified_session(session)
                fields={k:v for k,v in data.items() if k!="csrf"}
                return self.reply(200,review_picture_cut(
                    self.server.production_db_path,fields,actor))
            except PictureCutError as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (ProductionWebError,ProductionError,ValueError):
                return self.reply(400,{"ok":False,"reason":"invalid_picture_cut_review"})
            except (sqlite3.Error,OSError):
                return self.reply(503,{"ok":False,"reason":"picture_cut_storage_unavailable"})
        if path.startswith("/api/v1/video-results/"):
            try:
                actor=operator_from_verified_session(session)
                fields={k:v for k,v in data.items() if k!="csrf"}
                if path=="/api/v1/video-results/start":
                    with self.server.video_upload_lock:
                        result=begin_video_upload(
                            self.server.production_db_path,fields,actor)
                else:
                    actions={
                        "/api/v1/video-results/chunk": lambda:append_video_chunk(
                            self.server.production_db_path,fields,actor,
                            self.server.video_upload_lock),
                        "/api/v1/video-results/finish": lambda:finish_video_upload(
                            self.server.production_db_path,fields,actor,
                            self.server.video_upload_lock),
                        "/api/v1/video-results/review": lambda:review_video_take(
                            self.server.production_db_path,fields,actor)
                    }
                    result=actions[path]()
                return self.reply(200,result)
            except VideoResultError as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (ProductionWebError,ProductionError,TypeError,ValueError):
                return self.reply(400,{"ok":False,"reason":"invalid_video_result_fields"})
            except (sqlite3.Error,OSError):
                return self.reply(503,{"ok":False,"reason":"video_storage_unavailable"})
        if path.startswith("/api/v1/workflow/"):
            try:
                actor=operator_from_verified_session(session)
                fields={k:v for k,v in data.items() if k!="csrf"}
                action={"/api/v1/workflow/save":save_workflow_unit,
                        "/api/v1/workflow/review":review_workflow_unit}[path]
                result=action(self.server.production_db_path,fields,actor)
                return self.reply(201 if path.endswith("/save") else 200,result)
            except WorkflowError as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (ProductionWebError,ProductionError,ValueError):
                return self.reply(400,{"ok":False,"reason":"invalid_workflow_fields"})
            except (sqlite3.Error,OSError):
                return self.reply(503,{"ok":False,"reason":"workflow_storage_unavailable"})
        if path.startswith("/api/v1/scenes/"):
            try:
                actor=operator_from_verified_session(session)
                fields={k:v for k,v in data.items() if k!="csrf"}
                action={
                    "/api/v1/scenes/create":create_scene,
                    "/api/v1/scenes/update":update_scene,
                    "/api/v1/scenes/link":link_scene_visual,
                    "/api/v1/scenes/review":review_scene,
                }[path]
                result=action(self.server.production_db_path,fields,actor)
                return self.reply(201 if path.endswith("/create") else 200,result)
            except SceneError as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (ProductionWebError,ProductionError,ValueError):
                return self.reply(400,{"ok":False,"reason":"invalid_scene_fields"})
            except (sqlite3.Error,OSError):
                return self.reply(503,{"ok":False,"reason":"scene_storage_unavailable"})
        if path.startswith("/api/v1/characters/"):
            try:
                actor=operator_from_verified_session(session)
                fields={k:v for k,v in data.items() if k!="csrf"}
                action={
                    "/api/v1/characters/create":create_character,
                    "/api/v1/characters/update":update_character,
                    "/api/v1/characters/link":link_character_visual,
                    "/api/v1/characters/approve":approve_character_master,
                    "/api/v1/characters/assets/create":create_character_v2_asset,
                    "/api/v1/characters/assets/revise":revise_character_v2_asset,
                    "/api/v1/characters/assets/review":review_character_v2_asset,
                    "/api/v1/characters/shot-bindings/save":save_shot_character
                }[path]
                result=action(self.server.production_db_path,fields,actor)
                return self.reply(201 if path.endswith("/create") else 200,result)
            except CharacterError as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (ProductionWebError,ProductionError,ValueError):
                return self.reply(400,{"ok":False,"reason":"invalid_character_fields"})
            except (sqlite3.Error,OSError):
                return self.reply(503,{"ok":False,"reason":"character_storage_unavailable"})
        if path in ("/api/v1/production/visual/upload",
                    "/api/v1/production/visual/select"):
            try:
                actor=operator_from_verified_session(session)
                fields={k:v for k,v in data.items() if k!="csrf"}
                if path.endswith("/upload"):
                    out=upload_visual(self.server.production_db_path,fields,actor)
                    return self.reply(201,out)
                out=select_visual(self.server.production_db_path,fields,actor)
                return self.reply(200,out)
            except (VisualError,ProductionWebError) as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except (ProductionError,ValueError):
                return self.reply(400,{"ok":False,"reason":"invalid_visual_fields"})
            except (OSError,sqlite3.Error):
                return self.reply(503,{"ok":False,"reason":"visual_storage_unavailable"})
        if path=="/api/v1/production/action":
            try:
                result=create_from_web(
                    self.server.production_db_path,data,session)
                return self.reply(201,result)
            except ProductionWebError as exc:
                return self.reply(exc.status,{"ok":False,"reason":exc.reason})
            except Exception:
                return self.reply(503,{"ok":False,"reason":"production_storage_unavailable"})
        try:
            with closing(connect(self.server.db_path)) as db:
                out = decide(db, data.get("action"), shot_id=data.get("shot_id"),
                             revision=data.get("revision"), reason=data.get("reason", ""))
        except StudioError as exc:
            return self.reply(409, {"ok": False, "reason": str(exc)})
        except Exception:
            return self.reply(503, {"ok": False, "reason": "studio_storage_unavailable"})
        return self.reply(200, out)


def main():
    from argparse import ArgumentParser
    parser = ArgumentParser()
    parser.add_argument("--db", default=os.environ.get(
        "DIRECTOR_STUDIO_DB", "/var/lib/director-studio/studio.sqlite"))
    args = parser.parse_args()
    server = StudioServer(args.db)
    worker = threading.Thread(target=server.poller.loop, daemon=True)
    worker.start()
    # Single CPU lane for picture-cuts and approved A/V masters.
    # An owner request never directly starts FFmpeg on the HTTP thread.
    media_worker = threading.Thread(target=media_worker_loop,
        args=(server.production_db_path,lambda:server.is_running),
        daemon=True)
    media_worker.start()
    print("Director Studio V0.8 listening ONLY on 127.0.0.1:8900", flush=True)
    print("Connect using SSH local port forwarding; never publish this HTTP port", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.is_running = False
        server.poller.running = False
        server.server_close()


if __name__ == "__main__":
    main()
