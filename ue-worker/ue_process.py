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
    """Atomic one-writer JSON; no secrets from Epic in this protocol."""
    temp = path.with_name(path.name + ".tmp")
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if len(data) > 1200:
        raise ValueError("hero_interactive_payload_too_large")
    with temp.open("x", encoding="ascii") as fp:
        fp.write(data)
    temp.replace(path)


def _bridge_read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1200:
        raise ValueError("hero_interactive_invalid_receipt")
    return json.loads(path.read_text(encoding="ascii"))


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
                _bridge_write(heartbeat, {"format": HERO_BRIDGE_FORMAT,
                                          "job_id": ident, "updated": time.time()})
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
                try:
                    beat = _bridge_read(heartbeat)
                    if (type(beat) is not dict or
                            beat.get("format") != HERO_BRIDGE_FORMAT or
                            beat.get("job_id") != ident or
                            type(beat.get("updated")) not in (int, float) or
                            time.time() - beat["updated"] > 15):
                        _kill_tree(proc)
                        reason = "worker_heartbeat_lost"
                        break
                except (OSError, ValueError, TypeError):
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
        time.sleep(1)


if __name__ == "__main__" and sys.argv[1:] == ["--interactive-hero-runner"]:
    interactive_hero_runner_main()
