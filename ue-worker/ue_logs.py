"""Bounded allowlisted job-log tails. Never accepts a filesystem path."""
from __future__ import annotations

import re
from datetime import datetime, timezone

LOG_NAMES = {
    "unreal": "unreal.log",
    "preset": "preset.log",
    "hero_seed": "hero_seed.log",
    "hero_audit": "hero_audit.log",
    "render_01": "render_01.log",
    "render_13": "render_13.log",
    "render_26": "render_26.log",
    "render_31": "render_31.log",
    "render_lineup": "render_lineup.log",
    "render_gpt": "render_gpt.log",
    "render_gem": "render_gem.log",
    "render_ds": "render_ds.log",
    "render_cla": "render_cla.log",
    "render_zero": "render_zero.log",
}
MAX_TAIL_BYTES = 6000
SECRET_FILTERS = (
    (re.compile(r"(?i)(Authorization\s*[:=]\s*Bearer\s+)\S+"),
     r"\1[REDACTED]"),
    (re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/-]{16,}"),
     r"\1[REDACTED]"),
    (re.compile(r"(?i)\b(token|password|api[_-]?key|client[_-]?secret)\s*[:=]\s*[^\s;&]+"),
     r"\1=[REDACTED]"),
)


def log_tail(job_manager, job_id, kind):
    from ue_jobs import JobError
    # Entitlement is job-id-based; authenticated Hub never supplies paths.
    job_manager.lookup(job_id)
    if not isinstance(kind, str) or kind not in LOG_NAMES:
        raise JobError("invalid_log_kind")
    root = job_manager.root_factory()
    work = root / "Jobs" / job_id
    log = work / LOG_NAMES[kind]
    if work.is_symlink() or log.is_symlink() or not log.is_file():
        raise JobError("job_log_not_found")
    size = log.stat().st_size
    # Seek from the end: never read an entire potentially huge UE log.
    with log.open("rb") as stream:
        stream.seek(max(0, size - MAX_TAIL_BYTES))
        raw = stream.read(MAX_TAIL_BYTES)
    tail = raw.decode("utf-8", "replace")
    # Strip ANSI control sequences and nonprinting chars from logs.
    tail = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", tail)
    tail = "".join(c if c >= " " or c in "\r\n\t" else "?" for c in tail)
    for pattern, replacement in SECRET_FILTERS:
        tail = pattern.sub(replacement, tail)
    return {
        "ok": True, "job_id": job_id, "kind": kind,
        "tail": tail, "truncated": size > MAX_TAIL_BYTES,
        "source_bytes": size,
        "read_at": datetime.now(timezone.utc).isoformat(),
    }
