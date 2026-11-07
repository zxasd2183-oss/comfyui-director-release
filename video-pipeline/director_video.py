#!/usr/bin/env python3
"""Offline-first ComfyUI video shot planner and explicitly gated local executor.

No cloud GPU power controls, remote MCP endpoints, or secrets. Run only on the
same machine as ComfyUI. The H3 node graph must be an exported API workflow.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

COMFY = "http://127.0.0.1:8188"
MAX_JSON = 4_000_000
MAX_ASSET = 250_000_000
NODE = re.compile(r"^[0-9]+$")
SHOT = re.compile(r"^[A-Za-z0-9_-]{1,48}$")
PROMPT_HEADING = re.compile(r"^###\s+镜头\s+(\d+)")
PROMPT_BODY = re.compile(r"^-\s+\*\*主镜头提示：\*\*(.*)$")


class PlanError(ValueError):
    pass


def read_json(path):
    file = Path(path)
    if file.stat().st_size > MAX_JSON:
        raise PlanError("JSON file exceeds the 4MB planning limit")
    return json.loads(file.read_text(encoding="utf-8-sig"))


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".part")
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def validate_workflow(value):
    if not isinstance(value, dict):
        raise PlanError("Workflow must be a JSON object")
    if "nodes" in value or "links" in value:
        raise PlanError("UI workflow detected. Use ComfyUI: File -> Export Workflow (API)")
    graph = value.get("prompt", value)
    if not isinstance(graph, dict) or not 1 <= len(graph) <= 512:
        raise PlanError("API workflow must contain 1-512 node objects")
    for node_id, item in graph.items():
        if not isinstance(node_id, str) or not NODE.fullmatch(node_id):
            raise PlanError("API workflow node IDs must be numeric strings")
        if not isinstance(item, dict) or not isinstance(item.get("class_type"), str):
            raise PlanError("Each node needs class_type")
        if not isinstance(item.get("inputs"), dict):
            raise PlanError("Each node needs inputs object")
    return graph


def inspect_workflow(workflow):
    """Offline node/input inventory. Never display prompt, seed, model or path values."""
    graph = validate_workflow(workflow)
    return {
        "schema": 1, "node_count": len(graph), "api_format_only": True,
        "node_inventory": [
            {
                "id": ident, "class_type": node["class_type"],
                "inputs": [
                    {"name": key,
                     "kind": ("link" if isinstance(value, list) else
                              "structured" if isinstance(value, dict) else "literal")}
                    for key, value in sorted(node["inputs"].items())
                ],
            }
            for ident, node in sorted(graph.items(), key=lambda x: int(x[0]))
        ],
        "values_redacted": True,
        "network_calls": 0,
    }


def validate_bindings(mapping, graph):
    if not isinstance(mapping, dict) or "prompt" not in mapping:
        raise PlanError("bindings.json must include a prompt input mapping")
    allowed = {"prompt", "image", "seed", "frames", "fps"}
    if set(mapping) - allowed:
        raise PlanError("Unknown binding kind; allowed: prompt/image/seed/frames/fps")
    result = {}
    for field, entry in mapping.items():
        if not isinstance(entry, dict) or set(entry) != {"node", "input"}:
            raise PlanError("Each mapping requires exactly node and input")
        node_id, field_name = str(entry["node"]), entry["input"]
        if node_id not in graph or not isinstance(field_name, str):
            raise PlanError("A mapped node does not exist")
        if field_name not in graph[node_id]["inputs"]:
            raise PlanError("A mapped input does not exist in the exported graph")
        if isinstance(graph[node_id]["inputs"][field_name], (list, dict)):
            raise PlanError("Mapped value must be a literal input, not a node link")
        result[field] = (node_id, field_name)
    return result


def load_prompt_notes(path):
    if not path:
        return {}
    text = Path(path).read_text(encoding="utf-8-sig")
    prompts = {}
    active = None
    for line in text.splitlines():
        title = PROMPT_HEADING.match(line.strip())
        if title:
            active = f"{int(title.group(1)):02d}"
        body = PROMPT_BODY.match(line.strip())
        if body and active:
            prompts[active] = body.group(1).strip()
    return prompts


def load_shots(path, prompt_notes=None):
    prompt_notes = prompt_notes or {}
    path = Path(path)
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            entries = list(csv.DictReader(f))
    else:
        entries = read_json(path)
    if not isinstance(entries, list) or not 1 <= len(entries) <= 500:
        raise PlanError("Supply 1-500 shots as CSV or JSON list")
    result, seen = [], set()
    for pos, row in enumerate(entries, 1):
        if not isinstance(row, dict):
            raise PlanError("Each shot must be an object/CSV row")
        raw_id = str(row.get("shot_id") or row.get("镜号") or row.get("id") or pos).strip()
        shot_id = f"{int(raw_id):02d}" if raw_id.isdigit() else raw_id
        if not SHOT.fullmatch(shot_id) or shot_id in seen:
            raise PlanError("Shot IDs must be unique, 1-48 safe characters")
        seen.add(shot_id)
        try:
            seconds = float(row.get("seconds") or row.get("时长秒") or row.get("duration"))
        except (ValueError, TypeError):
            raise PlanError(f"Invalid duration for shot {shot_id}") from None
        if not 0 < seconds <= 30 or seconds != seconds:
            raise PlanError("Each generated clip must be between 0 and 30 seconds")
        description = str(
            prompt_notes.get(shot_id) or row.get("prompt") or
            row.get("主镜头提示") or row.get("画面与动作") or ""
        ).strip()
        if not 1 <= len(description) <= 12000:
            raise PlanError("Each shot needs a reasonable nonempty prompt")
        raw_seed = row.get("seed")
        seed = (int(raw_seed) if raw_seed not in ("", None) else
                int.from_bytes(hashlib.sha256(shot_id.encode()).digest()[:4], "big"))
        if not 0 <= seed < 2**63:
            raise PlanError("Invalid seed")
        image = str(row.get("image") or "").strip()
        if len(image) > 250 or ("\x00" in image):
            raise PlanError("Invalid image name")
        result.append(dict(shot_id=shot_id, seconds=seconds, prompt=description,
                           seed=seed, image=image))
    return result


def build_plan(workflow, bindings, shots, fps):
    graph = validate_workflow(workflow)
    slots = validate_bindings(bindings, graph)
    if not 1 <= fps <= 120:
        raise PlanError("FPS must be 1-120")
    jobs = []
    for shot in shots:
        copy_graph = copy.deepcopy(graph)
        default_seed = int.from_bytes(
            hashlib.sha256(shot["shot_id"].encode("utf-8")).digest()[:4], "big"
        )
        values = {"prompt": shot["prompt"], "seed": shot.get("seed", default_seed),
                  "frames": round(shot["seconds"] * fps), "fps": fps,
                  "image": shot.get("image", "")}
        for field, (node, input_name) in slots.items():
            if field == "image" and not values["image"]:
                raise PlanError("Image binding needs an explicit image for every shot")
            copy_graph[node]["inputs"][input_name] = values[field]
        jobs.append(dict(shot_id=shot["shot_id"], seconds=shot["seconds"],
                         frames=values["frames"], graph=copy_graph))
    return {"schema": 1, "fps": fps, "shot_count": len(jobs),
            "total_seconds": round(sum(s["seconds"] for s in shots), 3),
            "jobs": jobs, "api_format_only": True,
            "gpu_actions_performed": False}


def build_studio_handoff_plan(document, workflow, bindings, image=""):
    """Import ONE version-locked Studio shot without network or GPU access.

    A Studio handoff checksum is *not* a signature: the operator must obtain
    the JSON through their own protected Studio session and review it.
    This prevents accidentally submitting unapproved/upstream-incomplete clips,
    and leaves all Comfy execution under the existing explicit double opt-in.
    """
    if not isinstance(document, dict) or document.get("ok") is not True:
        raise PlanError("Invalid Studio handoff response")
    package = document.get("package")
    digest = document.get("package_sha256")
    if not isinstance(package, dict) or not isinstance(digest, str):
        raise PlanError("Missing Studio handoff checksum")
    if document.get("checksum_type") != "sha256_canonical_json_not_signature":
        raise PlanError("Unsupported Studio handoff checksum contract")
    canonical=json.dumps(package,sort_keys=True,ensure_ascii=False,
                         separators=(",",":")).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest()!=digest:
        raise PlanError("Studio handoff checksum mismatch")
    if package.get("schema")!="director_studio_video_handoff_v1":
        raise PlanError("Unsupported Studio handoff schema")
    if package.get("gpu_dispatch_authorized") is not False or (
        package.get("renderer_connected") is not False):
        raise PlanError("Studio package cannot grant GPU authorization")
    blockers=package.get("blockers")
    if blockers!=["video_render_executor_not_connected"]:
        raise PlanError("Studio upstream approvals incomplete; review blockers first")
    for field in ("project_id","episode_id","shot_id"):
        value=package.get(field)
        if not isinstance(value,str) or not SHOT.fullmatch(value):
            raise PlanError("Invalid Studio scope identifier")
    source=package.get("video_plan")
    upstream=package.get("upstream")
    if not isinstance(source,dict) or not isinstance(upstream,dict):
        raise PlanError("Missing Studio versioned production inputs")
    if source.get("status")!="in_review":
        raise PlanError("Studio video plan must be submitted for human review")
    if source.get("unit_id")!=package["shot_id"]:
        raise PlanError("Studio handoff video plan mismatches shot")
    for kind in ("settings","shot_plans","storyboards","white_models"):
        record=upstream.get(kind)
        if not isinstance(record,dict) or record.get("status")!="approved":
            raise PlanError("Studio upstream approval missing: "+kind)
    scene=package.get("scene")
    if not isinstance(scene,dict) or scene.get("status")!="approved":
        raise PlanError("Studio scene approval missing")
    props=package.get("props")
    if not isinstance(props,list) or any(
        not isinstance(p,dict) or not isinstance(p.get("version"),dict)
        or p["version"].get("status")!="approved" for p in props):
        raise PlanError("Studio prop approval missing")
    settings=upstream["settings"]["fields"]
    values=source.get("fields")
    if not isinstance(settings,dict) or not isinstance(values,dict):
        raise PlanError("Missing Studio video specification")
    try:
        fps=int(settings["fps"])
        width=int(settings["width"])
        height=int(settings["height"])
        duration_ms=package["duration_ms"]
        if type(duration_ms) is not int or not 0<duration_ms<=30000:
            raise ValueError()
        duration=duration_ms/1000
        if not 1<=fps<=120 or not 1<=width<=16384 or not 1<=height<=16384:
            raise ValueError()
        if "fps" in values and float(values["fps"])!=fps:
            raise ValueError()
        if "width" in values and float(values["width"])!=width:
            raise ValueError()
        if "height" in values and float(values["height"])!=height:
            raise ValueError()
        if "duration" in values and abs(float(values["duration"])-duration)>.001:
            raise ValueError()
    except (KeyError,ValueError,TypeError,OverflowError):
        raise PlanError("Video job does not match approved Studio output specification") from None
    prompt=values.get("prompt")
    if not isinstance(prompt,str) or not 1<=len(prompt.strip())<=12000:
        raise PlanError("Studio video prompt required")
    seed=values.get("seed","")
    if seed!="":
        try:
            seed=int(seed)
            if not 0<=seed<2**63:raise ValueError()
        except (TypeError,ValueError,OverflowError):
            raise PlanError("Invalid Studio video seed") from None
    else:seed=int.from_bytes(hashlib.sha256(package["shot_id"].encode()).digest()[:4],"big")
    if image and (not isinstance(image,str) or len(image)>200 or
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*",image)):
        raise PlanError("Studio image must be a safe ComfyUI input basename")
    graph=validate_workflow(workflow)
    slots=validate_bindings(bindings,graph)
    if ("image" in slots)!=bool(image):
        raise PlanError("Provide --image exactly when H3 binding requires an input image")
    plan=build_plan(workflow,bindings,[{"shot_id":package["shot_id"],
        "seconds":duration,"prompt":prompt,"seed":seed,"image":image}],fps)
    plan["studio_handoff"]={"project_id":package["project_id"],
        "episode_id":package["episode_id"],"shot_id":package["shot_id"],
        "video_revision":source["revision"],"package_sha256":digest,
        "checksum_is_signature":False,
        "manual_gpu_execution_required":True}
    return plan


def build_studio_episode_plan(document,workflow,bindings,images=None):
    """Prepare a complete approved episode as ONE offline local queue plan.

    No networking, GPU requests or implicit skipping of blocked shots.
    """
    images=images or {}
    if not isinstance(images,dict) or any(
        not isinstance(k,str) or not isinstance(v,str)
        for k,v in images.items()):
        raise PlanError("Invalid per-shot Comfy input image map")
    if not isinstance(document,dict) or document.get("ok") is not True:
        raise PlanError("Invalid Studio episode handoff")
    bundle=document.get("bundle")
    digest=document.get("bundle_sha256")
    if (not isinstance(bundle,dict) or not isinstance(digest,str) or
        document.get("checksum_type")!="sha256_canonical_json_not_signature"):
        raise PlanError("Missing Studio episode checksum")
    canonical=json.dumps(bundle,sort_keys=True,ensure_ascii=False,
        separators=(",",":")).encode()
    if hashlib.sha256(canonical).hexdigest()!=digest:
        raise PlanError("Studio episode handoff checksum mismatch")
    if bundle.get("schema")!="director_studio_episode_handoff_v1":
        raise PlanError("Unsupported Studio episode handoff schema")
    if bundle.get("gpu_dispatch_authorized") is not False:
        raise PlanError("Studio episode bundle cannot authorize GPU execution")
    if bundle.get("blocked") or bundle.get("all_ready") is not True:
        raise PlanError("Episode has blocked shots; no partial execution plan")
    ids=bundle.get("shot_ids")
    packages=bundle.get("packages")
    shot_count=bundle.get("shot_count")
    if (not isinstance(ids,list) or not isinstance(packages,list) or
        type(shot_count)!=int or not 1<=shot_count<=500 or
        len(ids)!=shot_count or len(packages)!=shot_count or
        len(set(ids))!=shot_count or not all(
            isinstance(x,str) and SHOT.fullmatch(x) for x in ids)):
        raise PlanError("Invalid Studio episode shot inventory")
    if set(images)-set(ids):
        raise PlanError("Per-shot image map contains unknown shots")
    jobs=[]
    receipts=[]
    fps=None
    duration_ms=0
    for sid,entry in zip(ids,packages):
        pkg=entry.get("package") if isinstance(entry,dict) else None
        if not isinstance(pkg,dict) or pkg.get("shot_id")!=sid or (
            pkg.get("project_id")!=bundle.get("project_id") or
            pkg.get("episode_id")!=bundle.get("episode_id")):
            raise PlanError("Studio episode shot order/source mismatch")
        single=build_studio_handoff_plan(entry,workflow,bindings,
                                          images.get(sid,""))
        if fps is None:fps=single["fps"]
        if single["fps"]!=fps:
            raise PlanError("Studio episode contains inconsistent frame rates")
        jobs.extend(single["jobs"])
        duration_ms+=pkg["duration_ms"]
        receipts.append(single["studio_handoff"])
    if type(bundle.get("total_duration_ms"))!=int or (
        duration_ms!=bundle["total_duration_ms"]):
        raise PlanError("Studio episode total duration mismatch")
    return {"schema":1,"fps":fps,"shot_count":shot_count,
        "total_seconds":round(duration_ms/1000,3),
        "jobs":jobs,"api_format_only":True,
        "gpu_actions_performed":False,
        "studio_episode_handoff":{
            "project_id":bundle["project_id"],
            "episode_id":bundle["episode_id"],
            "bundle_sha256":digest,
            "shot_receipts":receipts,
            "checksum_is_signature":False,
            "manual_gpu_execution_required":True}}


def load_plan(path):
    data = read_json(path)
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise PlanError("Unsupported plan")
    jobs = data.get("jobs")
    if not isinstance(jobs, list) or not 1 <= len(jobs) <= 500:
        raise PlanError("Invalid plan jobs")
    seen = set()
    for job in jobs:
        sid = job.get("shot_id")
        if not isinstance(sid, str) or not SHOT.fullmatch(sid) or sid in seen:
            raise PlanError("Invalid/duplicate shot ID")
        seen.add(sid)
        validate_workflow(job.get("graph"))
    return data


def plan_digest(plan):
    data = json.dumps(plan, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def db_open(path, plan):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(target))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
    con.execute("""CREATE TABLE IF NOT EXISTS runs (
        shot_id TEXT PRIMARY KEY, state TEXT NOT NULL, prompt_id TEXT,
        error_code TEXT, updated_at INTEGER NOT NULL)""")
    digest = plan_digest(plan)
    previous = con.execute("SELECT v FROM meta WHERE k='plan_digest'").fetchone()
    if previous and previous[0] != digest:
        con.close()
        raise PlanError("Plan changed. Use a NEW database path to avoid duplicated GPU jobs")
    with con:
        con.execute("INSERT OR IGNORE INTO meta(k,v) VALUES ('plan_digest',?)", (digest,))
        for job in plan["jobs"]:
            con.execute("""INSERT OR IGNORE INTO runs(shot_id,state,updated_at)
                VALUES (?,'pending',?)""", (job["shot_id"], int(time.time())))
    return con


def set_state(con, sid, state, prompt_id=None, error=None):
    with con:
        con.execute("""UPDATE runs SET state=?,prompt_id=COALESCE(?,prompt_id),
            error_code=?,updated_at=? WHERE shot_id=?""",
                    (state, prompt_id, error, int(time.time()), sid))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PlanError("ComfyUI attempted an unexpected redirect")


OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)


def comfy_json(endpoint, body=None):
    if not endpoint.startswith("/") or endpoint.startswith("//"):
        raise PlanError("Invalid local ComfyUI endpoint")
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(COMFY + endpoint, data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST" if body is not None else "GET")
    with OPENER.open(req, timeout=20) as stream:
        data = stream.read(MAX_JSON + 1)
    if len(data) > MAX_JSON:
        raise PlanError("ComfyUI returned oversized JSON")
    return json.loads(data)



# V0.7: validate against the real GPU installation without submitting a prompt.
# ComfyUI exposes a small per-node schema endpoint, avoiding the often large
# aggregate /object_info response. No dynamic hostnames or user-provided URLs.
NODE_CLASS = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,127}$")
MAX_NODE_TYPES = 128


def preflight_plan(plan, client=None):
    """Read-only node-presence + idle queue preflight; fail closed on uncertainty.

    ComfyUI has no atomic 'queue-if-idle' API. This check reduces accidental
    overlap but cannot exclude jobs submitted by another client afterward.
    """
    client = comfy_json if client is None else client
    if not isinstance(plan, dict) or not isinstance(plan.get("jobs"), list) or not plan["jobs"]:
        raise PlanError("Invalid video plan")
    classes = set()
    for job in plan["jobs"]:
        graph = validate_workflow(job.get("graph"))
        for node in graph.values():
            name = node["class_type"]
            if not NODE_CLASS.fullmatch(name):
                raise PlanError("Unsafe or unsupported node class name")
            classes.add(name)
    if len(classes) > MAX_NODE_TYPES:
        raise PlanError("Too many distinct ComfyUI node classes")
    schemas = {}
    for name in sorted(classes):
        schema = client("/object_info/" + urllib.parse.quote(name, safe=""))
        if (not isinstance(schema, dict) or name not in schema or
                not isinstance(schema[name], dict) or
                not isinstance(schema[name].get("input"), dict)):
            raise PlanError("Required node class is unavailable: " + name)
        schemas[name] = schema[name]["input"]

    # Only check explicit, literal inputs against server-advertised types and
    # bounds. Linked inputs are resolved by ComfyUI, not guessed here. Step is
    # a UI hint, so only min/max are enforced. Dynamic/unknown inputs are not
    # rejected here: the server validates those at POST /prompt.
    for job in plan["jobs"]:
        for node_id, node in job["graph"].items():
            metadata = schemas[node["class_type"]]
            fields = {}
            for section in ("required", "optional"):
                declared = metadata.get(section, {})
                if isinstance(declared, dict):
                    fields.update(declared)
            for field, value in node["inputs"].items():
                spec = fields.get(field)
                if (not isinstance(spec, (list, tuple)) or not spec or
                        isinstance(value, (dict, list))):
                    continue
                kind = spec[0]
                options = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
                if kind in ("INT", "FLOAT"):
                    if (isinstance(value, bool) or not isinstance(value, (float, int)) or
                            (kind == "INT" and not isinstance(value, int)) or
                            value != value):
                        raise PlanError("Input type mismatch at node " + node_id + "." + field)
                    minimum, maximum = options.get("min"), options.get("max")
                    if ((isinstance(minimum, (int, float)) and value < minimum) or
                            (isinstance(maximum, (int, float)) and value > maximum)):
                        raise PlanError("Input outside installed node bounds at " +
                                        node_id + "." + field)
                elif isinstance(kind, list) and value not in kind:
                    raise PlanError("Input choice unavailable in installed node at " +
                                    node_id + "." + field)
    queue = client("/queue")
    if not isinstance(queue, dict):
        raise PlanError("ComfyUI queue status unavailable")
    running, pending = queue.get("queue_running"), queue.get("queue_pending")
    if not isinstance(running, list) or not isinstance(pending, list):
        raise PlanError("ComfyUI queue response has invalid shape")
    if len(running) or len(pending):
        raise PlanError("ComfyUI queue is not idle; no new generation submitted")
    return {"ok": True, "node_types_checked": len(classes),
            "queue_running": 0, "queue_pending": 0,
            "shot_count": len(plan["jobs"]),
            "generation_submitted": False}


def submit_one(con, job):
    sid = job["shot_id"]
    set_state(con, sid, "submitting")
    try:
        response = comfy_json("/prompt", {"prompt": job["graph"]})
        pid = response.get("prompt_id") if isinstance(response, dict) else None
        if not isinstance(pid, str) or not re.fullmatch(r"[A-Za-z0-9-]{8,100}", pid):
            raise PlanError("No valid prompt_id in ComfyUI response")
    except urllib.error.HTTPError as exc:
        # 4xx means known validation rejection; 5xx may have queued the work.
        set_state(con, sid, "rejected" if 400 <= exc.code < 500 else "uncertain",
                  error="api_rejected" if 400 <= exc.code < 500 else "submit_unknown")
        return False
    except Exception:
        # A timed-out POST may already be queued. Never auto-retry or duplicate.
        set_state(con, sid, "uncertain", error="submit_unknown")
        return False
    set_state(con, sid, "queued", prompt_id=pid)
    return True


def safe_asset_name(value):
    return (isinstance(value, str) and 1 <= len(value) <= 200 and
            value not in {".", ".."} and "/" not in value and
            "\\" not in value and "\x00" not in value)


def outputs_from_history(history):
    files = []
    outputs = history.get("outputs", {})
    if not isinstance(outputs, dict):
        return files
    for node_id, value in outputs.items():
        if not isinstance(value, dict):
            continue
        for field in ("images", "gifs", "videos", "audio"):
            records = value.get(field)
            if not isinstance(records, list):
                continue
            for idx, asset in enumerate(records):
                if not isinstance(asset, dict):
                    continue
                filename = asset.get("filename")
                subfolder = asset.get("subfolder", "")
                kind = asset.get("type", "output")
                if not safe_asset_name(filename) or kind != "output":
                    continue
                if not isinstance(subfolder, str) or len(subfolder) > 200:
                    continue
                parts = subfolder.replace("\\", "/").split("/")
                if any(x in (".", "..") for x in parts) or subfolder.startswith("/"):
                    continue
                files.append({"node": str(node_id), "category": field,
                              "filename": filename, "subfolder": subfolder, "type": kind,
                              "index": idx})
    return files


def download_output(asset, dest):
    query = urllib.parse.urlencode({"filename": asset["filename"],
                                     "subfolder": asset["subfolder"],
                                     "type": "output"})
    req = urllib.request.Request(COMFY + "/view?" + query)
    tmp = dest.with_name(dest.name + ".part")
    checksum = hashlib.sha256()
    count = 0
    try:
        with OPENER.open(req, timeout=30) as inp, tmp.open("wb") as out:
            while True:
                chunk = inp.read(65536)
                if not chunk:
                    break
                count += len(chunk)
                if count > MAX_ASSET:
                    raise PlanError("Generated output exceeds the per-file download limit")
                out.write(chunk)
                checksum.update(chunk)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    return {"file": dest.name, "sha256": checksum.hexdigest(), "bytes": count}


def collect(con, plan, outdir, download=False):
    outdir = Path(outdir)
    collected = 0
    for job in plan["jobs"]:
        sid = job["shot_id"]
        row = con.execute("SELECT state,prompt_id FROM runs WHERE shot_id=?", (sid,)).fetchone()
        if not row or row[0] != "queued" or not row[1]:
            continue
        pid = row[1]
        try:
            result = comfy_json("/history/" + urllib.parse.quote(pid, safe=""))
            entry = result.get(pid) if isinstance(result, dict) else None
        except Exception:
            continue  # Still queued or ComfyUI currently unavailable.
        if not isinstance(entry, dict):
            continue
        status = entry.get("status", {})
        status = status if isinstance(status, dict) else {}
        if status.get("status_str") == "error":
            set_state(con, sid, "failed", error="comfy_execution_error")
            continue
        if status.get("status_str") != "success" and not status.get("completed"):
            continue
        artifacts = outputs_from_history(entry)
        directory = outdir / sid
        directory.mkdir(parents=True, exist_ok=True)
        downloads = []
        if download:
            try:
                for idx, asset in enumerate(artifacts):
                    name = f"{idx:03d}_{asset['filename']}"
                    downloads.append(download_output(asset, directory / name))
            except Exception:
                # Do not finalize the shot when an output copy was incomplete.
                continue
        atomic_json(directory / "manifest.json", {
            "shot_id": sid, "prompt_id": pid,
            "outputs": artifacts, "downloaded": downloads,
            "output_discovery_complete": True
        })
        set_state(con, sid, "done")
        collected += 1
    return collected



VIDEO_SUFFIXES = frozenset({".mp4"})
HASH = re.compile(r"^[a-f0-9]{64}$")


def file_checksum(path):
    digest = hashlib.sha256()
    total = 0
    with Path(path).open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            total += len(chunk)
            if total > MAX_ASSET:
                raise PlanError("Video asset exceeds configured maximum")
            digest.update(chunk)
    return digest.hexdigest(), total


def archived_clips(plan, results_dir):
    """Resolve exactly one verified downloaded MP4 per shot, in shot order."""
    root = Path(results_dir).resolve(strict=True)
    if not root.is_dir():
        raise PlanError("Output archive directory missing")
    clips = []
    for job in plan["jobs"]:
        sid = job["shot_id"]
        directory = Path(results_dir) / sid
        if directory.is_symlink() or not directory.is_dir():
            raise PlanError("Shot output directory missing or unsafe: " + sid)
        manifest_path = directory / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise PlanError("Downloaded manifest missing: " + sid)
        manifest = read_json(manifest_path)
        if not isinstance(manifest, dict) or manifest.get("shot_id") != sid:
            raise PlanError("Manifest does not match the video plan")
        downloads = manifest.get("downloaded")
        if not isinstance(downloads, list):
            raise PlanError("Manifest does not contain downloaded outputs")
        videos = [
            info for info in downloads
            if isinstance(info, dict) and isinstance(info.get("file"), str)
            and Path(info["file"]).suffix.lower() in VIDEO_SUFFIXES
        ]
        if len(videos) != 1:
            raise PlanError("Exactly one downloaded MP4 is required per shot: " + sid)
        info = videos[0]
        name = info["file"]
        if not safe_asset_name(name) or not HASH.fullmatch(str(info.get("sha256", ""))):
            raise PlanError("Unsafe or missing archived checksum")
        video = directory / name
        if video.is_symlink() or not video.is_file() or not video.resolve().is_relative_to(root):
            raise PlanError("Archived video path is invalid")
        actual_hash, total = file_checksum(video)
        if (actual_hash != info["sha256"] or
                type(info.get("bytes")) is not int or
                total != info["bytes"] or total == 0):
            raise PlanError("Archived video checksum/size mismatch: " + sid)
        clips.append(video.resolve())
    return clips


def export_studio_delivery(plan, results_dir, destination):
    """Make a single browser-importable folder for every collected MP4.

    Offline only. Copies verified collected files; never uploads, starts GPU,
    changes a source archive or claims server acceptance. Returns a manifest
    tied to the exact Studio episode/shot handoff revisions.
    """
    if not isinstance(plan,dict):
        raise PlanError("Invalid Studio delivery plan")
    episode=plan.get("studio_episode_handoff")
    single=plan.get("studio_handoff")
    receipts=(episode.get("shot_receipts") if isinstance(episode,dict)
              else [single] if isinstance(single,dict) else None)
    jobs=plan.get("jobs")
    if (not isinstance(jobs,list) or not jobs or not isinstance(receipts,list)
        or len(jobs)!=len(receipts) or len(jobs)>500):
        raise PlanError("Studio delivery requires versioned shot receipts")
    project_id=receipts[0].get("project_id")
    episode_id=receipts[0].get("episode_id")
    if (not isinstance(project_id,str) or not SHOT.fullmatch(project_id) or
        not isinstance(episode_id,str) or not SHOT.fullmatch(episode_id)):
        raise PlanError("Missing Studio project and episode receipt scope")
    if episode is not None and (episode.get("project_id")!=project_id or
        episode.get("episode_id")!=episode_id or not
        HASH.fullmatch(str(episode.get("bundle_sha256","")))):
        raise PlanError("Invalid Studio episode bundle receipt")

    shots=[]
    seen=set()
    for job,receipt in zip(jobs,receipts):
        if not isinstance(job,dict) or not isinstance(receipt,dict):
            raise PlanError("Invalid Studio delivery shot receipt")
        sid=job.get("shot_id")
        if (not isinstance(sid,str) or not SHOT.fullmatch(sid) or sid in seen
            or receipt.get("shot_id")!=sid
            or receipt.get("project_id")!=project_id
            or receipt.get("episode_id")!=episode_id
            or not HASH.fullmatch(str(receipt.get("package_sha256","")))
            or type(receipt.get("video_revision")) is not int
            or receipt["video_revision"]<1):
            raise PlanError("Studio delivery shot/receipt mismatch")
        seen.add(sid)
        shots.append(sid)
    if episode and (plan.get("shot_count")!=len(shots) or
        len(episode.get("shot_receipts",[]))!=len(shots)):
        raise PlanError("Studio delivery shot inventory incomplete")

    clips=archived_clips(plan,results_dir)
    dest=Path(destination)
    if (not dest.is_absolute() or dest.exists() or dest.is_symlink()
        or not dest.parent.is_dir() or dest.parent.is_symlink()):
        raise PlanError("Delivery destination must be a new absolute directory")
    staging=dest.parent/(".studio-delivery-"+os.urandom(12).hex())
    staging.mkdir(mode=0o700)
    try:
        items=[]
        for sid,receipt,clip in zip(shots,receipts,clips):
            manifest_path=clip.parent/"manifest.json"
            collected=read_json(manifest_path)
            prompt_id=collected.get("prompt_id")
            if (not isinstance(prompt_id,str) or
                not re.fullmatch(r"[A-Za-z0-9_-]{0,100}",prompt_id)):
                raise PlanError("Invalid collected ComfyUI prompt ID")
            src_hash,size=file_checksum(clip)
            if not 128<=size<=MAX_ASSET:
                raise PlanError("Studio delivery clip exceeds 250MB limit")
            target_name=f"SH_{sid}_{src_hash[:16]}.mp4"
            target=staging/target_name
            if target.exists():
                raise PlanError("Duplicate Studio delivery clip filename")
            with clip.open("rb") as src, target.open("xb") as out:
                shutil.copyfileobj(src,out,1024*1024)
                out.flush()
                os.fsync(out.fileno())
            if file_checksum(target)!=(src_hash,size):
                raise PlanError("Studio delivery copy hash mismatch")
            items.append({"shot_id":sid,"filename":target_name,
                "file_sha256":src_hash,"size_bytes":size,
                "prompt_id":prompt_id,
                "package_sha256":receipt["package_sha256"],
                "plan_revision":receipt["video_revision"]})
        inventory={"schema":"director_studio_video_delivery_v1",
            "project_id":project_id,"episode_id":episode_id,
            "shot_count":len(items),"shots":items,
            "episode_bundle_sha256":(
                episode["bundle_sha256"] if episode else None),
            "requires_owner_upload":True,
            "automatically_uploaded":False,"gpu_dispatch_authorized":False}
        digest=hashlib.sha256(json.dumps(inventory,sort_keys=True,
            ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
        atomic_json(staging/"manifest.json",{
            "ok":True,"manifest":inventory,"manifest_sha256":digest,
            "checksum_type":"sha256_canonical_json_not_signature"})
        os.rename(staging,dest)
        return {"ok":True,"directory":str(dest),"shot_count":len(items),
            "manifest_sha256":digest,"gpu_actions":0,"network_calls":0}
    except BaseException:
        shutil.rmtree(staging,ignore_errors=True)
        raise


def video_stream_signature(path, runner=None):
    """Require identical stream layouts before -c copy; never run a shell."""
    runner = subprocess.run if runner is None else runner
    result = runner([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,codec_name,width,height,pix_fmt,avg_frame_rate,sample_rate,channels",
        "-of", "json", str(path)
    ], capture_output=True, check=False, timeout=20)
    if result.returncode or len(result.stdout) > 64_000:
        raise PlanError("ffprobe cannot inspect one of the downloaded videos")
    try:
        streams = json.loads(result.stdout)["streams"]
    except (ValueError, TypeError, KeyError):
        raise PlanError("ffprobe returned invalid stream metadata") from None
    if not isinstance(streams, list) or not streams:
        raise PlanError("No video streams found")
    fields = ("codec_type", "codec_name", "width", "height", "pix_fmt",
              "avg_frame_rate", "sample_rate", "channels")
    signature = tuple(tuple(item.get(k) for k in fields) for item in streams
                      if isinstance(item, dict))
    video_count = sum(row[0] == "video" for row in signature)
    if video_count != 1 or len(signature) != len(streams):
        raise PlanError("Each clip must contain exactly one video stream")
    return signature


def quote_ffconcat(path):
    # ffconcat quoting (not a shell): quoted absolute paths, no command expansion.
    return "'" + str(path).replace("'", "'\\''") + "'"


def assemble_movie(plan, results_dir, movie_path, runner=None):
    """Join verified, compatible MP4 clips without transcoding or GPU calls."""
    runner = subprocess.run if runner is None else runner
    clips = archived_clips(plan, results_dir)
    movie = Path(movie_path)
    if movie.suffix.lower() != ".mp4" or movie.exists() or movie.is_symlink():
        raise PlanError("Choose a new .mp4 output filename")
    if not movie.parent.is_dir():
        raise PlanError("Movie output directory must already exist")
    first = video_stream_signature(clips[0], runner=runner)
    for clip in clips[1:]:
        if video_stream_signature(clip, runner=runner) != first:
            raise PlanError("Video/audio streams differ; refusing unsafe lossless concatenation")

    concat_name = None
    staging_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8",
                prefix=".director-shots-", suffix=".ffconcat",
                dir=str(movie.parent), delete=False) as target:
            concat_name = target.name
            target.write("ffconcat version 1.0\n")
            for clip in clips:
                target.write("file " + quote_ffconcat(clip) + "\n")
        fd, staging_name = tempfile.mkstemp(
            prefix=".director-joined-", suffix=".mp4", dir=str(movie.parent))
        os.close(fd)
        response = runner(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                 "-f", "concat", "-safe", "0", "-i", concat_name,
                 "-map", "0", "-c", "copy", "-movflags", "+faststart",
                 "-y", staging_name], capture_output=True, check=False,
                 timeout=3600)
        if response.returncode or not Path(staging_name).is_file() or Path(staging_name).stat().st_size == 0:
            raise PlanError("ffmpeg concatenation failed; no final movie was published")
        # Hard-link publish is atomic and refuses to overwrite an existing output.
        os.link(staging_name, movie)
    finally:
        if staging_name:
            Path(staging_name).unlink(missing_ok=True)
        if concat_name:
            Path(concat_name).unlink(missing_ok=True)
    return {"ok": True, "clips": len(clips), "movie": str(movie),
            "bytes": movie.stat().st_size, "gpu_calls": 0}



def verify_completed_shot(results_dir, shot_id):
    """Reject image-only or damaged results; ONE real downloaded MP4 is required."""
    root = Path(results_dir)
    folder = root / shot_id
    manifest_path = folder / "manifest.json"
    if (root.is_symlink() or folder.is_symlink() or
            manifest_path.is_symlink() or not manifest_path.is_file()):
        raise PlanError("Completed shot output missing or unsafe: " + shot_id)
    manifest = read_json(manifest_path)
    if (not isinstance(manifest, dict) or manifest.get("shot_id") != shot_id or
            not isinstance(manifest.get("prompt_id"), str) or
            not isinstance(manifest.get("downloaded"), list)):
        raise PlanError("Completed shot manifest invalid: " + shot_id)
    mp4 = [f for f in manifest["downloaded"] if isinstance(f, dict)
           and isinstance(f.get("file"), str) and
           Path(f["file"]).suffix.lower() == ".mp4"]
    if len(mp4) != 1:
        raise PlanError("Completed shot must have exactly one downloaded MP4: " + shot_id)
    item = mp4[0]
    if (not safe_asset_name(item["file"]) or
            not HASH.fullmatch(str(item.get("sha256", ""))) or
            type(item.get("bytes")) is not int or item["bytes"] < 128):
        raise PlanError("Completed shot archive metadata invalid: " + shot_id)
    movie = folder / item["file"]
    if movie.is_symlink() or not movie.is_file():
        raise PlanError("Completed shot MP4 missing or unsafe: " + shot_id)
    actual_hash, actual_bytes = file_checksum(movie)
    if (actual_hash != item["sha256"] or actual_bytes != item["bytes"]):
        raise PlanError("Completed shot MP4 checksum mismatch: " + shot_id)
    return {"shot_id": shot_id, "bytes": actual_bytes, "sha256": actual_hash}


def run_episode(plan, db_path, results_dir, delivery_dir=None, *,
                poll_seconds=10, shot_timeout=7200):
    """One local GPU operator command, sequential generation + checked download.

    Resumes queued/done records after restart without re-submitting; rejects
    uncertain, rejected and failed records rather than silently retrying them.
    Uses OS file lock so concurrent operator invocations cannot double-spend.
    Does not start/stop GPU or change Studio owner authorization.
    """
    if not 1 <= poll_seconds <= 60 or not 60 <= shot_timeout <= 28800:
        raise PlanError("Invalid polling interval or per-shot deadline")
    target = Path(db_path)
    out = Path(results_dir)
    if target.is_symlink() or out.is_symlink():
        raise PlanError("Refuse symlinked queue database or result directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and not out.is_dir():
        raise PlanError("Results path must be a directory")
    import fcntl
    lock_path = target.with_name(target.name + ".runner.lock")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PlanError("Another GPU episode runner is already active") from None
        con = db_open(target, plan)
        try:
            finished = 0
            for job in plan["jobs"]:
                sid = job["shot_id"]
                record = con.execute(
                    "SELECT state,prompt_id FROM runs WHERE shot_id=?", (sid,)).fetchone()
                if not record:
                    raise PlanError("Run database missing shot " + sid)
                state, prompt_id = record
                if state == "done":
                    verify_completed_shot(out, sid)
                    finished += 1
                    continue
                if state == "pending":
                    # Only the current shot is submitted; ComfyUI must be idle.
                    preflight_plan({"jobs": [job]})
                    if not submit_one(con, job):
                        raise PlanError("Submission failed/uncertain for shot " + sid +
                                        "; inspect local status before retrying")
                elif state != "queued" or not prompt_id:
                    raise PlanError("Shot " + sid + " is " + state +
                                    "; cannot safely auto-retry or advance")
                deadline = time.monotonic() + shot_timeout
                while True:
                    collect(con, {"jobs": [job]}, out, download=True)
                    record = con.execute(
                        "SELECT state FROM runs WHERE shot_id=?", (sid,)).fetchone()
                    current = record[0]
                    if current == "done":
                        verify_completed_shot(out, sid)
                        finished += 1
                        break
                    if current != "queued":
                        raise PlanError("Shot " + sid + " ended in " + current +
                                        "; no duplicate job will be submitted")
                    if time.monotonic() >= deadline:
                        raise PlanError("Shot " + sid + " timed out; queued job can "
                                        "be resumed, never resubmit it")
                    time.sleep(poll_seconds)
            delivery = None
            if delivery_dir is not None:
                delivery = export_studio_delivery(plan, out, delivery_dir)
            return {"ok": True, "completed_shots": finished,
                    "shot_count": len(plan["jobs"]),
                    "delivery": delivery, "automatic_gpu_submission": True,
                    "automatic_studio_upload": False}
        finally:
            con.close()
    finally:
        os.close(descriptor)


def run_cli(argv=None):
    parser = argparse.ArgumentParser(description="Director offline-first ComfyUI shot pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect", help="Print redacted workflow nodes and binding fields")
    inspect.add_argument("--workflow", required=True)
    prepare = sub.add_parser("prepare", help="Offline validation and API plan generation")
    prepare.add_argument("--workflow", required=True)
    prepare.add_argument("--bindings", required=True)
    prepare.add_argument("--shots", required=True)
    prepare.add_argument("--prompts", help="Optional markdown per-shot prompt file")
    prepare.add_argument("--fps", type=int, default=24)
    prepare.add_argument("--out", required=True)
    studio = sub.add_parser("prepare-studio",
        help="Offline import of a versioned Studio video handoff (no GPU)")
    studio.add_argument("--package", required=True,
        help="Owner-exported Studio handoff JSON")
    studio.add_argument("--workflow", required=True)
    studio.add_argument("--bindings", required=True)
    studio.add_argument("--image", default="",
        help="Already-approved basename in ComfyUI input directory, if bound")
    studio.add_argument("--out", required=True)
    batch = sub.add_parser("prepare-studio-batch",
        help="Offline ALL-shot Studio episode import; refuses incomplete bundles")
    batch.add_argument("--package", required=True)
    batch.add_argument("--workflow", required=True)
    batch.add_argument("--bindings", required=True)
    batch.add_argument("--images",
        help="JSON object mapping shot IDs to approved local image basenames")
    batch.add_argument("--out", required=True)
    for cmd in ("preflight", "submit", "collect", "status"):
        item = sub.add_parser(cmd)
        item.add_argument("--plan", required=True)
        if cmd != "preflight":
            item.add_argument("--db", required=True)
        if cmd == "submit":
            item.add_argument("--execute", action="store_true")
            item.add_argument("--acknowledge-gpu-cost", action="store_true")
            item.add_argument("--max-jobs", type=int, default=1)
        elif cmd == "collect":
            item.add_argument("--out", required=True)
            item.add_argument("--download", action="store_true")
    episode_run = sub.add_parser("run-episode",
        help="On-GPU sequential render, resume, download & optional Studio delivery")
    episode_run.add_argument("--plan", required=True)
    episode_run.add_argument("--db", required=True)
    episode_run.add_argument("--results", required=True)
    episode_run.add_argument("--delivery",
        help="NEW absolute Studio owner-importable directory (optional)")
    episode_run.add_argument("--poll-seconds", type=int, default=10)
    episode_run.add_argument("--shot-timeout", type=int, default=7200)
    episode_run.add_argument("--execute", action="store_true")
    episode_run.add_argument("--acknowledge-gpu-cost", action="store_true")
    delivery = sub.add_parser("export-studio-delivery",
        help="Make one offline browser-uploadable folder of all verified MP4 clips")
    delivery.add_argument("--plan",required=True)
    delivery.add_argument("--results",required=True)
    delivery.add_argument("--out",required=True)
    merge = sub.add_parser("assemble", help="Verify archived MP4 clips and concatenate locally")
    merge.add_argument("--plan", required=True)
    merge.add_argument("--results", required=True)
    merge.add_argument("--movie", required=True)
    args = parser.parse_args(argv)
    if args.command == "inspect":
        print(json.dumps(inspect_workflow(read_json(args.workflow)), ensure_ascii=False, indent=2))
        return 0
    if args.command == "prepare":
        plan = build_plan(read_json(args.workflow), read_json(args.bindings),
                          load_shots(args.shots, load_prompt_notes(args.prompts)), args.fps)
        atomic_json(args.out, plan)
        print(f"Prepared {plan['shot_count']} shots, {plan['total_seconds']} seconds; NO GPU call")
        return 0
    if args.command == "prepare-studio-batch":
        image_map=read_json(args.images) if args.images else {}
        plan=build_studio_episode_plan(read_json(args.package),
            read_json(args.workflow),read_json(args.bindings),image_map)
        atomic_json(args.out,plan)
        print("Prepared %d Studio shots / %.3f s OFFLINE; no GPU call. "
              "Any future submit requires --execute AND --acknowledge-gpu-cost."
              %(plan["shot_count"],plan["total_seconds"]))
        return 0
    if args.command == "prepare-studio":
        plan=build_studio_handoff_plan(read_json(args.package),
            read_json(args.workflow),read_json(args.bindings),args.image)
        atomic_json(args.out,plan)
        print("Prepared ONE audited Studio shot (no GPU call). "
              "Future submit requires --execute AND --acknowledge-gpu-cost.")
        return 0
    plan = load_plan(args.plan)
    if args.command == "run-episode":
        if not args.execute or not args.acknowledge_gpu_cost:
            raise PlanError("run-episode requires BOTH --execute and "
                            "--acknowledge-gpu-cost; no job was submitted")
        print(json.dumps(run_episode(
            plan, args.db, args.results, args.delivery,
            poll_seconds=args.poll_seconds, shot_timeout=args.shot_timeout),
            ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "export-studio-delivery":
        print(json.dumps(export_studio_delivery(plan,args.results,args.out),
                         ensure_ascii=False,sort_keys=True))
        return 0
    if args.command == "assemble":
        print(json.dumps(assemble_movie(plan, args.results, args.movie), ensure_ascii=False))
        return 0
    if args.command == "preflight":
        print(json.dumps(preflight_plan(plan), ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "submit" and not (args.execute and args.acknowledge_gpu_cost):
        print("DRY RUN: no tasks submitted. Need BOTH --execute and --acknowledge-gpu-cost")
        return 0
    if args.command == "submit" and not 1 <= args.max_jobs <= 100:
        raise PlanError("--max-jobs must be 1-100")
    con = db_open(args.db, plan)
    try:
        if args.command == "submit":
            checked = preflight_plan(plan)
            print("Preflight OK: %d node types present, ComfyUI queue idle" % checked["node_types_checked"])
            attempted = 0
            for job in plan["jobs"]:
                state = con.execute("SELECT state FROM runs WHERE shot_id=?",
                                    (job["shot_id"],)).fetchone()[0]
                if state != "pending":
                    continue
                if not submit_one(con, job):
                    print(f"Submission stopped at shot {job['shot_id']}; check local status")
                    break
                attempted += 1
                if attempted >= args.max_jobs:
                    break
            print(f"Submitted {attempted} jobs to LOCAL ComfyUI")
        elif args.command == "collect":
            n = collect(con, plan, args.out, download=args.download)
            print(f"Collected {n} completed jobs; no new generation submitted")
        else:
            rows = con.execute(
                "SELECT shot_id,state,COALESCE(prompt_id,''),COALESCE(error_code,'') "
                "FROM runs ORDER BY shot_id").fetchall()
            for row in rows:
                print("\t".join(row))
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run_cli())
    except (PlanError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
