"""Job-owned Unreal subprocess management: cancellable, bounded, no user commands.

Only trusted UE Worker Python files call run_fixed(). A job controller never
accepts a PID from the network; the PID must come from our Popen handle.
"""
from __future__ import annotations

import contextvars
import os
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
import ctypes
import getpass
import hashlib
import json
import re
import secrets
import sys

_CURRENT = contextvars.ContextVar("director_ue_job_controller", default=None)


class JobCancelled(RuntimeError):
    pass


def _kill_tree(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":
        # taskkill.exe is chosen by an absolute trusted Windows system path.
        # The PID is an integer from Popen, never from caller input.
        taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
        try:
            subprocess.run(
                [str(taskkill), "/PID", str(int(proc.pid)), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=10, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    if proc.poll() is None:
        try:
            proc.kill()
        except (OSError, ProcessLookupError):
            pass
    try:
        proc.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass


class ProcessController:
    def __init__(self):
        self.lock = threading.Lock()
        self.cancel_requested = threading.Event()
        self.process = None

    def register(self, process):
        with self.lock:
            self.process = process
            stop = self.cancel_requested.is_set()
        if stop:
            _kill_tree(process)

    def clear(self, process):
        with self.lock:
            if self.process is process:
                self.process = None

    def cancel(self):
        # Fast acknowledgement: the runner checks this flag every 500ms,
        # then terminates its own process tree. No network timeout.
        self.cancel_requested.set()


@contextmanager
def job_scope(controller):
    token = _CURRENT.set(controller)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def run_fixed(command, root, logfile, timeout, env, timeout_reason, failed_reason):
    """Run the source-defined UE command with a tracked process and hard timeout.

    This is *not* an exposed generic command-execution RPC. Callers must be
    bundled, audited Worker functions; HTTP requests never contain arguments.
    """
    from ue_jobs import JobError
    controller = _CURRENT.get()
    if controller is not None and controller.cancel_requested.is_set():
        raise JobCancelled("job_cancelled")
    deadline = time.monotonic() + timeout
    with logfile.open("wb") as log:
        process = subprocess.Popen(
            command, cwd=str(root), env=env,
            stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if controller is not None:
            controller.register(process)
        try:
            while True:
                if controller is not None and controller.cancel_requested.is_set():
                    _kill_tree(process)
                    raise JobCancelled("job_cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _kill_tree(process)
                    raise JobError(timeout_reason)
                try:
                    rc = process.wait(timeout=min(remaining, 0.5))
                    break
                except subprocess.TimeoutExpired:
                    continue
            if controller is not None and controller.cancel_requested.is_set():
                raise JobCancelled("job_cancelled")
            if rc != 0:
                raise JobError(failed_reason)
        finally:
            if controller is not None:
                controller.clear(process)
            if process.poll() is None:
                _kill_tree(process)


# Only one reviewed MetaHuman cloud-rig operation is available in the
# interactive Windows login session. No general command/argv/shell bridge.
# The long-lived foreground runner starts in the user's real logon session
# from a locally registered TASK_LOGON_INTERACTIVE_TOKEN task.
HERO_BRIDGE_FORMAT = "director_ue_hero_interactive_v1"
HERO_BRIDGE_TIMEOUT = 780
HERO_BRIDGE_ID = re.compile(r"[a-f0-9]{32}\Z")
HERO_BRIDGE_ROOT = Path(r"C:\DirectorVirtualStudio")
HERO_BRIDGE_SUBDIR = ("JobStatus", "InteractiveHero")


def _hero_bridge_path(root):
    return root.joinpath(*HERO_BRIDGE_SUBDIR)


def _bridge_safe_parent(path, stop):
    p = path
    while True:
        if p.is_symlink() or getattr(p, "is_junction", lambda: False)():
            raise ValueError("hero_interactive_reparse_point")
        if p == stop:
            break
        if p == p.parent:
            raise ValueError("hero_interactive_outside_workspace")
        p = p.parent


def _bridge_write(path, payload):
    """Atomic one-writer JSON; retry short Windows sharing-violation races.

    The authenticated Worker and interactive runner each own distinct files.
    Never modify the JSON in place: readers must see a complete receipt.
    """
    temp = path.with_name(path.name + ".tmp")
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if len(data) > 1200:
        raise ValueError("hero_interactive_payload_too_large")
    with temp.open("x", encoding="ascii") as fp:
        fp.write(data)
    for attempt in range(8):
        try:
            temp.replace(path)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.05)


def _bridge_read(path):
    """Read one atomic snapshot through a single handle, bounded to 1200 B."""
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise ValueError("hero_interactive_invalid_receipt")
    with path.open("rb") as fp:
        raw = fp.read(1201)
    if not 1 <= len(raw) <= 1200:
        raise ValueError("hero_interactive_invalid_receipt")
    return json.loads(raw.decode("ascii"))


def _hero_bridge_is_windows():
    return os.name == "nt"


def interactive_hero_status(root=None):
    root = HERO_BRIDGE_ROOT if root is None else Path(root)
    try:
        if root != HERO_BRIDGE_ROOT:
            return {"available": False, "reason": "workspace_mismatch"}
        base = _hero_bridge_path(root)
        ready = base / "ready.json"
        _bridge_safe_parent(ready, root)
        data = _bridge_read(ready)
        if (type(data) is not dict or
                set(data) != {"format", "user", "session_id", "pid", "updated"} or
                data["format"] != HERO_BRIDGE_FORMAT or
                type(data["user"]) is not str or not 1 <= len(data["user"]) <= 80 or
                data["user"].lower() in {"system", "directorueworker"} or
                type(data["session_id"]) is not int or not 1 <= data["session_id"] <= 9999 or
                type(data["pid"]) is not int or data["pid"] < 1 or
                type(data["updated"]) not in (int, float) or
                not 0 <= time.time() - data["updated"] <= 8):
            return {"available": False, "reason": "interactive_runner_not_current"}
        return {"available": True, "user": data["user"],
                "session_id": data["session_id"]}
    except (OSError, ValueError, TypeError, UnicodeError):
        return {"available": False, "reason": "interactive_runner_not_started"}


def _bridge_controller_cancelled():
    controller = _CURRENT.get()
    return bool(controller is not None and controller.cancel_requested.is_set())


def _bridge_signal_cancel(folder, ident):
    signal = folder / "cancel" / (ident + ".json")
    if not signal.exists():
        _bridge_write(signal, {"format": HERO_BRIDGE_FORMAT, "job_id": ident})


def run_interactive_hero_rig(root, work, timeout=HERO_BRIDGE_TIMEOUT):
    """Wait for the SAME Windows logon session to run the hardcoded rig task.

    This call is only from the verified v200 hero path, after source hashes
    and immutable project configuration have been checked. It never accepts
    executable, arguments, paths or a session identity from an MCP client.
    """
    from ue_jobs import JobError
    root, work = Path(root), Path(work)
    if not _hero_bridge_is_windows() or root != HERO_BRIDGE_ROOT:
        raise JobError("hero_interactive_windows_required")
    if not HERO_BRIDGE_ID.fullmatch(work.name) or work.parent != root / "Jobs":
        raise JobError("hero_interactive_work_invalid")
    state = interactive_hero_status(root)
    if state.get("available") is not True:
        raise JobError("hero_interactive_login_session_required")
    folder = _hero_bridge_path(root)
    _bridge_safe_parent(folder, root)
    for name in ("requests", "results", "cancel", "heartbeat", "claimed"):
        directory = folder / name
        _bridge_safe_parent(directory, root)
        if not directory.is_dir():
            raise JobError("hero_interactive_bridge_not_configured")
    ident, nonce = work.name, secrets.token_hex(16)
    requested = time.time()
    request = folder / "requests" / (ident + ".json")
    result = folder / "results" / (ident + ".json")
    heartbeat = folder / "heartbeat" / (ident + ".json")
    if request.exists() or result.exists() or heartbeat.exists():
        raise JobError("hero_interactive_job_collision")
    _bridge_write(heartbeat, {"format": HERO_BRIDGE_FORMAT,
                              "job_id": ident, "updated": requested})
    _bridge_write(request, {"format": HERO_BRIDGE_FORMAT,
                            "task": "hero_rig_v200", "job_id": ident,
                            "nonce": nonce, "created": requested})
    deadline = time.monotonic() + min(timeout, HERO_BRIDGE_TIMEOUT) + 20
    next_heartbeat = 0
    try:
        while time.monotonic() < deadline:
            if _bridge_controller_cancelled():
                _bridge_signal_cancel(folder, ident)
                # The UI Worker cannot abandon an interactive UE process before
                # its own user-session process confirms termination.
                stopped_by = time.monotonic() + 15
                while time.monotonic() < stopped_by and not result.exists():
                    time.sleep(0.5)
                if not result.exists():
                    raise JobError("hero_interactive_cancel_unconfirmed")
                raise JobCancelled("job_cancelled")
            if result.exists():
                data = _bridge_read(result)
                if (type(data) is not dict or
                        set(data) != {"format", "job_id", "nonce", "exit_code",
                                      "session_id", "user", "reason"} or
                        data["format"] != HERO_BRIDGE_FORMAT or
                        data["job_id"] != ident or data["nonce"] != nonce or
                        type(data["session_id"]) is not int or
                        data["session_id"] != state["session_id"] or
                        data["user"] != state["user"] or
                        type(data["exit_code"]) is not int):
                    raise JobError("hero_interactive_receipt_invalid")
                if data["exit_code"] != 0:
                    raise JobError("hero_interactive_ue_failed")
                return
            if time.monotonic() >= next_heartbeat:
                try:
                    _bridge_write(heartbeat, {"format": HERO_BRIDGE_FORMAT,
                                              "job_id": ident, "updated": time.time()})
                except (OSError, ValueError):
                    _bridge_signal_cancel(folder, ident)
                    raise JobError("hero_interactive_heartbeat_write_failed") from None
                next_heartbeat = time.monotonic() + 2
            if interactive_hero_status(root).get("available") is not True:
                _bridge_signal_cancel(folder, ident)
                raise JobError("hero_interactive_runner_disconnected")
            time.sleep(0.5)
        _bridge_signal_cancel(folder, ident)
        raise JobError("hero_interactive_timeout")
    finally:
        # Cancel files remain briefly for the interactive runner to observe.
        # Never delete a request/claim before the other process has exited.
        pass



def interactive_hero_job_diagnostic(root, job_id):
    """Sanitized, read-only bridge receipt inspection for one existing rig job.

    No arbitrary paths, raw file contents, credentials, user names, command
    lines, or account-session tokens are returned.
    """
    root = Path(root)
    if root != HERO_BRIDGE_ROOT or type(job_id) is not str or not HERO_BRIDGE_ID.fullmatch(job_id):
        return {"available": False, "reason": "invalid_diagnostic_target"}
    folder = _hero_bridge_path(root)
    report = {"available": True}
    for name in ("requests", "claimed", "heartbeat", "cancel", "results"):
        path = folder / name / (job_id + ".json")
        try:
            _bridge_safe_parent(path, root)
            if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                report[name] = "unsafe"
            elif not path.is_file():
                report[name] = "missing"
            else:
                report[name] = "present"
        except (OSError, ValueError):
            report[name] = "unreadable"
    if report["results"] == "present":
        path = folder / "results" / (job_id + ".json")
        try:
            data = _bridge_read(path)
            if (type(data) is not dict or
                    set(data) != {"format", "job_id", "nonce", "exit_code",
                                  "session_id", "user", "reason"} or
                    data.get("format") != HERO_BRIDGE_FORMAT or
                    data.get("job_id") != job_id or
                    type(data.get("exit_code")) is not int or
                    data.get("reason") not in {
                        "not_started", "preflight_or_launch_failed", "finished",
                        "editor_failed", "cancelled_or_timed_out",
                        "worker_heartbeat_lost"}):
                report["results"] = "invalid"
            else:
                report["results"] = "valid"
                report["process_exit"] = ("zero" if data["exit_code"] == 0
                                          else "nonzero")
                report["process_reason"] = data["reason"]
        except (OSError, ValueError, TypeError, UnicodeError):
            report["results"] = "invalid"
    receipt = root / "Jobs" / job_id / "hero_rig_result.json"
    try:
        _bridge_safe_parent(receipt, root)
        if receipt.is_symlink() or getattr(receipt, "is_junction", lambda: False)():
            report["rig_receipt"] = "unsafe"
        elif not receipt.is_file():
            report["rig_receipt"] = "missing"
        elif not 1 <= receipt.stat().st_size <= 6000:
            report["rig_receipt"] = "invalid_size"
        else:
            content = json.loads(receipt.read_text(encoding="utf-8"))
            if type(content) is not dict:
                report["rig_receipt"] = "invalid"
            elif content.get("ok") is True:
                report["rig_receipt"] = "success_unverified"
            elif (content.get("ok") is False and
                  type(content.get("reason")) is str and
                  re.fullmatch(r"hero_rig_failed_(?:identity|source|clone|register|cloud_request|rig_readback|save|release)",
                               content["reason"])):
                report["rig_receipt"] = "failed"
                report["rig_stage"] = content["reason"]
            else:
                report["rig_receipt"] = "invalid"
    except (OSError, ValueError, TypeError, UnicodeError):
        report["rig_receipt"] = "unreadable"
    report["mutations_performed"] = False
    return report


def hero_rig_editor_log_diagnostic(root, started_at, finished_at):
    """Read-only, time-scoped classification of a failed rig's UE project log.

    Never return raw Editor lines, URLs, credentials, usernames or arbitrary
    paths. Timestamp correlation prevents old sign-in errors being mistaken
    for this failed run. No additional Unreal/cloud request is made.
    """
    from datetime import datetime, timedelta, timezone

    root = Path(root)
    if root != HERO_BRIDGE_ROOT:
        return {"available": False, "reason": "invalid_diagnostic_target"}
    try:
        started = datetime.fromisoformat(started_at)
        finished = datetime.fromisoformat(finished_at)
        if (started.tzinfo is None or finished.tzinfo is None or
                not started < finished <= started + timedelta(minutes=30)):
            raise ValueError("invalid_job_window")
        started = started.astimezone(timezone.utc)
        finished = finished.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        return {"available": False, "reason": "invalid_job_window"}

    path = (root / "HeroProjects" / "CHAR_GPT" / "Saved" /
            "Logs" / "DirectorHeroGPT.log")
    try:
        _bridge_safe_parent(path, root)
        if not path.is_file() or path.is_symlink():
            return {"available": False, "reason": "editor_log_unavailable"}
        meta = path.stat()
        if not 1 <= meta.st_size <= 128 * 1024 * 1024:
            return {"available": False, "reason": "editor_log_unavailable"}
        updated = datetime.fromtimestamp(meta.st_mtime, timezone.utc)
        if not (started - timedelta(minutes=2) <= updated <=
                finished + timedelta(minutes=5)):
            return {"available": False, "reason": "editor_log_not_correlated"}
        with path.open("rb") as fp:
            fp.seek(max(0, meta.st_size - 4 * 1024 * 1024))
            data = fp.read(4 * 1024 * 1024 + 1)
    except (OSError, ValueError, OverflowError):
        return {"available": False, "reason": "editor_log_unavailable"}
    if len(data) > 4 * 1024 * 1024:
        return {"available": False, "reason": "editor_log_changed"}

    # Every classified line must carry UE's own UTC time within this job.
    stamp = re.compile(
        r"^\[(\d{4})\.(\d{2})\.(\d{2})-(\d{2})\.(\d{2})\.(\d{2}):\d+\]")
    signals = set()
    scoped_lines = 0
    readback_exception = "not_observed"
    for line in data.decode("utf-8", errors="replace").splitlines():
        m = stamp.match(line)
        if m is None:
            continue
        try:
            when = datetime(*[int(x) for x in m.groups()], tzinfo=timezone.utc)
        except ValueError:
            continue
        if not started - timedelta(seconds=30) <= when <= finished + timedelta(seconds=30):
            continue
        scoped_lines += 1
        value = line.casefold()
        # This marker is emitted by our fixed Unreal script after the
        # blocking cloud call. It distinguishes an unavailable Python
        # editor property from a present-but-false DNA result.
        if ("director hero rig blocked phase=rig_readback" in value and
                "exception_class=" in value):
            match = re.search(r"exception_class=([A-Za-z_]{1,48})", line)
            if match:
                cls = match.group(1)
                readback_exception = (cls if cls in {
                    "RuntimeError", "AttributeError", "TypeError",
                    "ValueError", "Exception"} else "other")
        if ("logeosauth" in value and
                "no existing persistent auth credentials" in value):
            signals.add("no_epic_persistent_credentials")
        if ("logmetahumanauth" in value and
                ("login failed" in value or "eos_invalidauth" in value)):
            signals.add("epic_signin_failed")
        if ("auto-rigging of face failed" in value or
                ("logmetahumancharactereditor" in value and
                 "rigging" in value and ("failed" in value or "error" in value))):
            signals.add("cloud_autorig_failed")
        if ("loghttp" in value and "timed out" in value):
            signals.add("http_request_timeout")
        if ("logpython" in value and
                ("error" in value or "traceback" in value or "exception" in value)):
            signals.add("editor_python_error")
    return {"available": True, "status": "analyzed" if scoped_lines else
            "no_correlated_timestamped_lines", "signals": sorted(signals),
            "readback_exception": readback_exception,
            "mutations_performed": False}


def _windows_session_identity():
    if os.name != "nt":
        raise RuntimeError("interactive_windows_required")
    username_buffer = ctypes.create_unicode_buffer(256)
    count = ctypes.c_ulong(len(username_buffer))
    if not ctypes.windll.advapi32.GetUserNameW(username_buffer, ctypes.byref(count)):
        raise RuntimeError("interactive_username_unavailable")
    session = ctypes.c_ulong(0)
    if not ctypes.windll.kernel32.ProcessIdToSessionId(
        os.getpid(), ctypes.byref(session)
    ) or session.value < 1:
        raise RuntimeError("interactive_logon_session_required")
    user = username_buffer.value
    if not user or user.lower() in {"system", "directorueworker"}:
        raise RuntimeError("interactive_account_not_permitted")
    return user, int(session.value)


def _interactive_hero_preflight(root, job_id):
    """Fail closed before an Epic request if the pinned assets drifted."""
    from agent import trusted_hero_project_manifest
    from ue_previs import (
        GPT_HERO_FACE_SOURCE_JOB, GPT_HERO_FACE_SOURCE_SHA256,
        GPT_HERO_AMBER_SOURCE_JOB, GPT_HERO_AMBER_SOURCE_SHA256,
        GPT_HERO_SOURCE_JOB, GPT_HERO_SOURCE_SHA256,
    )
    project = root / "HeroProjects" / "CHAR_GPT" / "DirectorHeroGPT.uproject"
    script = Path(__file__).resolve().with_name("unreal_create_previs_preset.py")
    if (project.is_symlink() or not project.is_file() or
            script.is_symlink() or not script.is_file()):
        raise ValueError("hero_interactive_source_missing")
    if not trusted_hero_project_manifest(json.loads(project.read_text("utf-8"))):
        raise ValueError("hero_interactive_project_untrusted")
    base = project.parent / "Content" / "Director" / "Candidates" / "EP01"
    sources = (
        (base / "HeroFaces" / ("J" + GPT_HERO_FACE_SOURCE_JOB) /
         "MHC_CHAR_GPT_FaceContourV1.uasset", GPT_HERO_FACE_SOURCE_SHA256),
        (base / "HeroLooks" / ("J" + GPT_HERO_AMBER_SOURCE_JOB) /
         "MHC_CHAR_GPT_AmberV1.uasset", GPT_HERO_AMBER_SOURCE_SHA256),
        (base / "HeroBuilds" / ("J" + GPT_HERO_SOURCE_JOB) /
         "MHC_CHAR_GPT.uasset", GPT_HERO_SOURCE_SHA256),
    )
    if any(p.is_symlink() or not p.is_file() or
           hashlib.sha256(p.read_bytes()).hexdigest() != expected
           for p, expected in sources):
        raise ValueError("hero_interactive_source_changed")
    target = (base / "HeroRigs" / ("J" + job_id) /
              "MHC_CHAR_GPT_RigV1.uasset")
    if target.exists() or target.is_symlink():
        raise ValueError("hero_interactive_candidate_collision")
    return project, script


def _interactive_hero_once(root, folder, ticket, user, session):
    # Use the actual GUI Editor for on-screen Epic login, not
    # UnrealEditor-Cmd.exe (a headless commandlet binary).
    editor = Path(r"C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe")
    ident, nonce = ticket["job_id"], ticket["nonce"]
    work = root / "Jobs" / ident
    result = folder / "results" / (ident + ".json")
    cancel = folder / "cancel" / (ident + ".json")
    heartbeat = folder / "heartbeat" / (ident + ".json")
    exit_code, reason = -1, "not_started"
    try:
        project, script = _interactive_hero_preflight(root, ident)
        if not work.is_dir() or work.is_symlink():
            raise ValueError("hero_interactive_work_missing")
        receipt = work / "hero_rig_result.json"
        if receipt.exists():
            raise ValueError("hero_interactive_receipt_collision")
        env = os.environ.copy()  # Current RDP account's HKCU / Epic profile
        env["DIRECTOR_UE_JOB_ID"] = ident
        env["DIRECTOR_UE_REVIEW_MODE"] = "hero_rig_v200"
        env["DIRECTOR_UE_RESULT_FILE"] = str(receipt)
        # Crucially NOT -unattended: Epic may show account authorization.
        if not editor.is_file() or editor.is_symlink():
            raise ValueError("hero_interactive_gui_editor_missing")
        # Epic UE 5.8 Python docs: ExecutePythonScript launches the FULL
        # project editor. -run=pythonscript is a headless commandlet and must
        # not be used for the signed-in RDP user's cloud authorization.
        argv = [str(editor), str(project),
                "-ExecutePythonScript=" + str(script),
                "-nop4", "-nosplash", "-NoSound", "-log"]
        with (work / "hero_rig.log").open("wb") as log:
            proc = subprocess.Popen(argv, cwd=str(root), env=env,
                                    stdout=log, stderr=subprocess.STDOUT)
            reason = "editor_failed"
            deadline = time.monotonic() + HERO_BRIDGE_TIMEOUT
            next_ready = 0.0
            last_valid_worker_heartbeat = time.monotonic()
            while True:
                # The authenticated Worker must keep seeing this same user /
                # session while a potentially long cloud request is active.
                if time.monotonic() >= next_ready:
                    _bridge_write(folder / "ready.json", {
                        "format": HERO_BRIDGE_FORMAT, "user": user,
                        "session_id": session, "pid": os.getpid(),
                        "updated": time.time(),
                    })
                    next_ready = time.monotonic() + 2
                if cancel.exists() or time.monotonic() >= deadline:
                    _kill_tree(proc)  # PID comes exclusively from local Popen
                    reason = "cancelled_or_timed_out"
                    break
                # A single NTFS replace/read race is not proof of a lost
                # controller. Require 15 seconds without ANY valid, fresh
                # heartbeat before killing the owned editor process.
                valid_heartbeat = False
                try:
                    beat = _bridge_read(heartbeat)
                    valid_heartbeat = (
                        type(beat) is dict and
                        beat.get("format") == HERO_BRIDGE_FORMAT and
                        beat.get("job_id") == ident and
                        type(beat.get("updated")) in (int, float) and
                        0 <= time.time() - beat["updated"] <= 15)
                except (OSError, ValueError, TypeError, UnicodeError):
                    pass
                if valid_heartbeat:
                    last_valid_worker_heartbeat = time.monotonic()
                elif time.monotonic() - last_valid_worker_heartbeat > 15:
                    _kill_tree(proc)
                    reason = "worker_heartbeat_lost"
                    break
                code = proc.poll()
                if code is not None:
                    exit_code = code
                    reason = "finished" if code == 0 else "editor_failed"
                    break
                time.sleep(0.5)
    except (OSError, ValueError, RuntimeError):
        reason = "preflight_or_launch_failed"
    _bridge_write(result, {"format": HERO_BRIDGE_FORMAT, "job_id": ident,
                           "nonce": nonce, "exit_code": exit_code,
                           "session_id": session, "user": user, "reason": reason})


def interactive_hero_runner_main():
    user, session = _windows_session_identity()
    root = HERO_BRIDGE_ROOT
    folder = _hero_bridge_path(root)
    for part in (folder, *(folder / name for name in
                 ("requests", "results", "cancel", "heartbeat", "claimed"))):
        _bridge_safe_parent(part, root)
        part.mkdir(parents=True, exist_ok=True)
    ready = folder / "ready.json"
    while True:
        _bridge_write(ready, {"format": HERO_BRIDGE_FORMAT, "user": user,
                              "session_id": session, "pid": os.getpid(),
                              "updated": time.time()})
        for request in sorted((folder / "requests").glob("*.json"))[:8]:
            try:
                if request.is_symlink() or not HERO_BRIDGE_ID.fullmatch(request.stem):
                    continue
                item = _bridge_read(request)
                if (type(item) is not dict or
                        set(item) != {"format", "task", "job_id", "nonce", "created"} or
                        item["format"] != HERO_BRIDGE_FORMAT or
                        item["task"] != "hero_rig_v200" or
                        item["job_id"] != request.stem or
                        not HERO_BRIDGE_ID.fullmatch(item["nonce"]) or
                        type(item["created"]) not in (int, float) or
                        not 0 <= time.time() - item["created"] <= 20):
                    continue
                claim = folder / "claimed" / request.name
                try:
                    with claim.open("x", encoding="ascii") as claimed:
                        claimed.write(item["nonce"])
                except FileExistsError:
                    continue
                _interactive_hero_once(root, folder, item, user, session)
            except (OSError, ValueError, TypeError, UnicodeError):
                # Never run untrusted inputs or an unverified project.
                continue
        try:
            _codex_poll(root, session)
        except (OSError, ValueError, TypeError, UnicodeError):
            pass
        time.sleep(1)


# The existing RDP user's interactive-token task is the ONLY Codex executor.
# Never accept remote executable paths or thread IDs; the user opts in locally.
CODEX_FMT = "director_codex_bridge_v1"
CODEX_ID = re.compile(r"[a-f0-9]{32}\Z")
CODEX_THREAD = re.compile(r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}\Z")
CODEX_ROOT = HERO_BRIDGE_ROOT / "JobStatus" / "CodexBridge"


def _codex_path(root):
    return root / "JobStatus" / "CodexBridge"


def _codex_json(path):
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise ValueError("unsafe_codex_file")
    with path.open("rb") as f:
        raw = f.read(8193)
    if not 1 <= len(raw) <= 8192:
        raise ValueError("invalid_codex_file")
    return json.loads(raw)


def _codex_write(path, payload):
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True,
                     ensure_ascii=True).encode("ascii")
    if not 1 <= len(raw) <= 8192:
        raise ValueError("invalid_codex_payload")
    temp = path.with_name(path.name + "." + secrets.token_hex(8) + ".pending")
    try:
        with temp.open("xb") as out:
            out.write(raw)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _codex_consent():
    local = os.environ.get("LOCALAPPDATA")
    if not local or not Path(local).is_absolute():
        return None
    directory = Path(local) / "DirectorCodexBridge"
    path = directory / "consent.json"
    try:
        if directory.is_symlink() or not path.is_file() or path.stat().st_size > 512:
            return None
        doc = _codex_json(path)
        if (type(doc) is not dict or set(doc) !=
                {"format", "enabled", "thread_id"} or
                doc["format"] != CODEX_FMT or doc["enabled"] is not True or
                type(doc["thread_id"]) is not str or
                not CODEX_THREAD.fullmatch(doc["thread_id"])):
            return None
        return doc["thread_id"]
    except (OSError, ValueError, TypeError, UnicodeError):
        return None


def _codex_binary():
    local = os.environ.get("LOCALAPPDATA")
    if not local or not Path(local).is_absolute():
        return None
    folder = Path(local) / "OpenAI" / "Codex" / "bin"
    if folder.is_symlink() or not folder.is_dir():
        return None
    choices = []
    for path in list(folder.glob("*/codex.exe"))[:24]:
        if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
            continue
        try:
            if path.resolve().is_relative_to(folder.resolve()):
                choices.append((path.stat().st_mtime, path))
        except OSError:
            continue
    return max(choices)[1] if choices else None


def _codex_message_valid(text):
    return (type(text) is str and 1 <= len(text) <= 1200 and
            bool(text.strip()) and len(text.encode("utf-8")) <= 3000 and
            all(ord(ch) >= 32 or ch in "\n\t" for ch in text))


def codex_bridge_status(root=HERO_BRIDGE_ROOT):
    if root != HERO_BRIDGE_ROOT:
        return {"available": False, "reason": "workspace_mismatch"}
    try:
        path = _codex_path(root) / "ready.json"
        _bridge_safe_parent(path, root)
        doc = _codex_json(path)
        if (type(doc) is not dict or set(doc) !=
                {"format", "enabled", "session_id", "updated"} or
                doc["format"] != CODEX_FMT or
                doc["enabled"] is not True or
                type(doc["session_id"]) is not int or
                not 1 <= doc["session_id"] <= 9999 or
                type(doc["updated"]) not in (int, float) or
                not 0 <= time.time() - doc["updated"] <= 8):
            return {"available": False, "reason": "codex_consent_or_session_missing"}
        return {"available": True, "session_id": doc["session_id"],
                "scope": "single_locally_consented_thread"}
    except (OSError, ValueError, TypeError, UnicodeError):
        return {"available": False, "reason": "codex_bridge_not_running"}


def codex_stage(message, root=HERO_BRIDGE_ROOT):
    if root != HERO_BRIDGE_ROOT or not _codex_message_valid(message):
        return {"ok": False, "reason": "codex_message_invalid"}
    if codex_bridge_status(root).get("available") is not True:
        return {"ok": False, "reason": "codex_local_consent_required"}
    try:
        base = _codex_path(root)
        folder = base / "requests"
        _bridge_safe_parent(folder, root)
        if not folder.is_dir() or sum(1 for _ in folder.glob("*.json")) >= 4:
            return {"ok": False, "reason": "codex_queue_not_ready"}
        ident = secrets.token_hex(16)
        _codex_write(folder / (ident + ".json"),
                     {"format": CODEX_FMT, "id": ident,
                      "created": time.time(), "message": message})
        return {"ok": True, "request_id": ident, "state": "staged",
                "gui_delivery_confirmed": False, "completed": False}
    except (OSError, ValueError, TypeError):
        return {"ok": False, "reason": "codex_bridge_unavailable"}


def codex_lookup(ident, root=HERO_BRIDGE_ROOT):
    if type(ident) is not str or not CODEX_ID.fullmatch(ident):
        return {"ok": False, "reason": "invalid_codex_request_id"}
    if root != HERO_BRIDGE_ROOT:
        return {"ok": False, "reason": "workspace_mismatch"}
    try:
        base = _codex_path(root)
        receipt = base / "receipts" / (ident + ".json")
        _bridge_safe_parent(receipt, root)
        if receipt.is_file():
            obj = _codex_json(receipt)
            if (type(obj) is not dict or set(obj) !=
                    {"format", "id", "state"} or
                    obj["format"] != CODEX_FMT or obj["id"] != ident or
                    obj["state"] not in ("queued_by_cli", "failed")):
                raise ValueError("invalid_codex_receipt")
            return {"ok": True, "request_id": ident, "state": obj["state"],
                    "gui_delivery_confirmed": False, "completed": False}
        if (base / "claims" / (ident + ".json")).is_file():
            return {"ok": True, "request_id": ident, "state": "claimed_unknown_delivery",
                    "gui_delivery_confirmed": False, "completed": False}
        if (base / "requests" / (ident + ".json")).is_file():
            return {"ok": True, "request_id": ident, "state": "staged",
                    "gui_delivery_confirmed": False, "completed": False}
    except (OSError, ValueError, TypeError, UnicodeError):
        return {"ok": False, "reason": "invalid_codex_receipt"}
    return {"ok": False, "reason": "codex_request_not_found"}


def _codex_poll(root, session):
    """No shell, no new app-server, no credentials, one real RDP user session."""
    if root != HERO_BRIDGE_ROOT or not 1 <= session <= 9999:
        return
    base = _codex_path(root)
    for name in (None, "requests", "claims", "receipts"):
        directory = base if name is None else base / name
        _bridge_safe_parent(directory, root)
        directory.mkdir(parents=True, exist_ok=True)
    thread = _codex_consent()
    exe = _codex_binary() if thread else None
    _codex_write(base / "ready.json",
                 {"format": CODEX_FMT, "enabled": bool(thread and exe),
                  "session_id": session, "updated": time.time()})
    for path in sorted((base / "requests").glob("*.json"))[:4]:
        if path.is_symlink() or not CODEX_ID.fullmatch(path.stem):
            continue
        try:
            payload = _codex_json(path)
            valid = (type(payload) is dict and set(payload) ==
                     {"format", "id", "created", "message"} and
                     payload["format"] == CODEX_FMT and
                     payload["id"] == path.stem and
                     type(payload["created"]) in (int, float) and
                     0 <= time.time() - payload["created"] <= 90 and
                     _codex_message_valid(payload["message"]))
            claim = base / "claims" / path.name
            try:
                with claim.open("x", encoding="ascii") as fp:
                    fp.write(path.stem)
            except FileExistsError:
                continue
            state = "failed"
            if valid and thread and exe:
                try:
                    result = subprocess.run(
                        [str(exe), "queue", "--thread", thread,
                         "--message", payload["message"]],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, timeout=30, check=False,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    if result.returncode == 0:
                        state = "queued_by_cli"
                except (OSError, subprocess.TimeoutExpired):
                    pass
            _codex_write(base / "receipts" / path.name,
                         {"format": CODEX_FMT, "id": path.stem, "state": state})
            path.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError, UnicodeError):
            # Claimed requests are never replayed automatically.
            continue



if __name__ == "__main__" and sys.argv[1:] == ["--interactive-hero-runner"]:
    interactive_hero_runner_main()
