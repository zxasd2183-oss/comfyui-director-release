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
