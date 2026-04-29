"""
kw-filter MCP Web Server
========================
FastAPI server with auto replace-on-upload and auto restore.

Keywords are read from  mcp/keywords.txt  by default.
Override with env var:  KW_KEYWORDS_FILE=/path/to/keywords.txt

Run:
    python mcp/server.py              # 0.0.0.0:8000
    python mcp/server.py --port 9000
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel
import uvicorn

from kw_tools import cmd_replace, cmd_restore  # noqa: E402

# ── Paths ─────────────────────────────────────────────────────────────────────

MCP_DIR       = Path(__file__).parent
STORAGE       = MCP_DIR / "storage"           # tokenised uploads (visible via list_files)
RESTORED      = MCP_DIR / "restored"          # restore output (NOT visible via list_files)
MAPPING_FILE  = STORAGE / "_mapping.json"     # global accumulated mapping
KEYWORDS_FILE = Path(os.environ.get("KW_KEYWORDS_FILE", MCP_DIR / "keywords.txt"))

STORAGE.mkdir(exist_ok=True)
RESTORED.mkdir(exist_ok=True)

# ── LLM integration (optional) ────────────────────────────────────────────────
# Set KW_LLM_URL to enable local LLM keyword extraction.
# Example (Ollama): KW_LLM_URL=http://localhost:11434  KW_LLM_MODEL=llama3
LLM_URL   = os.environ.get("KW_LLM_URL", "")
LLM_MODEL = os.environ.get("KW_LLM_MODEL", "llama3")

# ── ai4privacy (optional) ─────────────────────────────────────────────────────
# Must be set before importing ai4privacy so the model is loaded from local cache.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
_ai4privacy_protect = None
try:
    from ai4privacy import protect as _ai4privacy_protect  # type: ignore
    print("[kw-filter] ai4privacy loaded successfully", flush=True)
except ImportError:
    print("[kw-filter] ai4privacy not installed — PII detection disabled", flush=True)
except Exception as _e:
    print(f"[kw-filter] ai4privacy failed to load: {_e}", flush=True)

# ── Content analysis — regex patterns ────────────────────────────────────────
_IP_RE = re.compile(
    r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}'
    r'(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b'
)
_DOMAIN_RE = re.compile(
    r'\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)'
    r'+[a-zA-Z]{2,}\b'
)
_HASH_RE = re.compile(r'\b[0-9a-fA-F]{32,128}\b')
_HASH_SUBTYPES: dict[int, str] = {32: "MD5", 40: "SHA1", 64: "SHA256", 128: "SHA512"}


def _ip_subtype(ip_str: str) -> str:
    try:
        addr = ipaddress.ip_address(ip_str)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            return "PRIVATE"
    except ValueError:
        pass
    return "PUBLIC"


def _analyze_with_llm(content: str) -> list[str]:
    """Extract keywords via local LLM. Configure KW_LLM_URL + KW_LLM_MODEL to enable.

    Ollama example:
        # resp = httpx.post(f"{LLM_URL}/api/generate", json={
        #     "model": LLM_MODEL,
        #     "prompt": f"List all sensitive keywords, IPs, and IOCs. One per line:\\n\\n{content[:4000]}",
        #     "stream": False,
        # }, timeout=120)
        # return [l.strip() for l in resp.json().get("response","").splitlines() if l.strip()]
    """
    if not LLM_URL:
        return []
    # TODO: implement LLM call
    return []


def _analyze_with_ai4privacy(content: str) -> list[dict]:
    """Extract PII using ai4privacy. Returns [{value, labels: {label: count}}]."""
    if _ai4privacy_protect is None:
        return []
    try:
        result = _ai4privacy_protect(content, classify_pii=True, verbose=True)
        agg: dict[str, dict[str, int]] = {}
        for r in result.get("replacements", []):
            v = r.get("value", "").strip()
            label = r.get("label", "PII")
            if not v:
                continue
            agg.setdefault(v, {})
            agg[v][label] = agg[v].get(label, 0) + 1
        return [{"value": v, "labels": lc} for v, lc in agg.items()]
    except Exception as e:
        print(f"[kw-filter] ai4privacy error: {e}", flush=True)
        return []


def _analyze_content(content: str) -> list[dict]:
    seen: set[str] = set()
    seen_lower: set[str] = set()
    items: list[dict] = []

    # 1. IPs
    for m in _IP_RE.finditer(content):
        v = m.group()
        if v in seen:
            continue
        seen.add(v); seen_lower.add(v.lower())
        sub = _ip_subtype(v)
        items.append({"value": v, "type": "IP", "subtype": sub,
                      "auto_select": False})

    ip_set = {i["value"] for i in items}

    # 2. Domains (skip anything that parsed as an IP)
    for m in _DOMAIN_RE.finditer(content):
        v = m.group().lower()
        if v in seen or v in ip_set:
            continue
        seen.add(v); seen_lower.add(v)
        items.append({"value": v, "type": "DOMAIN", "subtype": None,
                      "auto_select": False})

    # 3. Hashes — greedy match gives longest hex run, classify by exact length
    for m in _HASH_RE.finditer(content):
        v = m.group().lower()
        sub = _HASH_SUBTYPES.get(len(v))
        if not sub or v in seen:
            continue
        seen.add(v); seen_lower.add(v)
        items.append({"value": v, "type": "HASH", "subtype": sub,
                      "auto_select": False})

    # 4. LLM-extracted keywords (placeholder)
    for v in _analyze_with_llm(content):
        v = v.strip()
        if v and v not in seen:
            seen.add(v); seen_lower.add(v.lower())
            items.append({"value": v, "type": "LLM", "subtype": None,
                          "auto_select": False})

    # 5. ai4privacy PII detection
    for pii in _analyze_with_ai4privacy(content):
        v = pii["value"]
        if v.lower() in seen_lower:
            continue
        seen.add(v); seen_lower.add(v.lower())
        labels: dict[str, int] = pii["labels"]
        primary = max(labels, key=labels.__getitem__) if labels else "PII"
        items.append({"value": v, "type": "PII", "subtype": primary,
                      "labels": labels, "auto_select": False})

    return items


# ── IP blacklist ──────────────────────────────────────────────────────────────
# mcp/ip_blacklist.txt — one IP per line; lines starting with # are comments
IP_BLACKLIST_FILE = MCP_DIR / "ip_blacklist.txt"
_RESTRICTED = ("/docs", "/openapi.json", "/redoc", "/keywords", "/restored")


def _load_blacklist() -> set[str]:
    if not IP_BLACKLIST_FILE.exists():
        return set()
    lines = IP_BLACKLIST_FILE.read_text(encoding="utf-8").splitlines()
    return {l.strip() for l in lines if l.strip() and not l.startswith("#")}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _require_keywords() -> Path:
    if not KEYWORDS_FILE.exists():
        raise HTTPException(
            503,
            f"keywords.txt not found at {KEYWORDS_FILE}. "
            "Create mcp/keywords.txt or set KW_KEYWORDS_FILE env var."
        )
    return KEYWORDS_FILE


def _meta(file_id: str) -> dict:
    d = STORAGE / file_id
    if not d.exists():
        raise HTTPException(404, f"file_id {file_id!r} not found")
    return json.loads((d / "_meta.json").read_text())


def _store(name: str, content: bytes, extra: dict | None = None) -> dict:
    file_id = str(uuid.uuid4())
    d = STORAGE / file_id
    d.mkdir()
    (d / name).write_bytes(content)
    meta = {"file_id": file_id, "name": name, "size": len(content), **(extra or {})}
    (d / "_meta.json").write_text(json.dumps(meta, ensure_ascii=False))
    return meta


def _run_replace(src_name: str, src_bytes: bytes) -> tuple[bytes, int]:
    """Replace keywords in src_bytes; merge new tokens into global mapping.
    Returns (tokenized_bytes, tokens_created)."""
    kw = _require_keywords()

    with tempfile.TemporaryDirectory() as _tmp:
        tmp = Path(_tmp)
        target = tmp / src_name
        target.write_bytes(src_bytes)
        tmp_mapping = tmp / "mapping.json"

        ns = argparse.Namespace(
            keywords=str(kw),
            target=str(target),
            mapping=str(tmp_mapping),
            backup=False,
            dry_run=False,
        )
        cmd_replace(ns)

        if not tmp_mapping.exists() or not json.loads(tmp_mapping.read_text()):
            raise HTTPException(422, "no keywords matched — check keywords.txt")

        new_mapping: dict = json.loads(tmp_mapping.read_text())

        # Accumulate into global mapping (tokens are unique UUIDs, no collision)
        global_mapping: dict = {}
        if MAPPING_FILE.exists():
            global_mapping = json.loads(MAPPING_FILE.read_text())
        global_mapping.update(new_mapping)
        MAPPING_FILE.write_text(json.dumps(global_mapping, ensure_ascii=False, indent=2))

        return target.read_bytes(), len(new_mapping)


def _run_restore(name: str, content: str) -> bytes:
    """Restore tokens in content using global mapping. Returns restored bytes."""
    if not MAPPING_FILE.exists():
        raise HTTPException(422, "no mapping available — upload a file first to build the mapping")

    with tempfile.TemporaryDirectory() as _tmp:
        tmp = Path(_tmp)
        target = tmp / name
        target.write_text(content, encoding="utf-8")
        shutil.copy(MAPPING_FILE, tmp / "mapping.json")

        ns = argparse.Namespace(
            mapping=str(tmp / "mapping.json"),
            target=str(target),
            backup=False,
            dry_run=False,
        )
        cmd_restore(ns)

        return target.read_bytes()


# ── App ───────────────────────────────────────────────────────────────────────

class _IPGuard(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if any(request.url.path.startswith(p) for p in _RESTRICTED):
            blacklist = _load_blacklist()
            if blacklist:
                ip = (
                    request.headers.get("X-Real-IP")
                    or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                    or (request.client.host if request.client else "")
                )
                if ip in blacklist:
                    return Response("Forbidden", status_code=403)
        return await call_next(request)


app = FastAPI(
    title="kw-filter Server",
    description=(
        "Upload files → auto replace with keywords.txt. "
        "GET /files/{id} → tokenised content safe to send to AI. "
        "POST /restore → AI output restored to original values."
    ),
    version="2.0.0",
)
app.add_middleware(_IPGuard)


# ── Web UI ───────────────────────────────────────────────────────────────────

_UI_FILE = MCP_DIR / "templates" / "index.html"

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def web_ui():
    return HTMLResponse(_UI_FILE.read_text(encoding="utf-8"))


# ── File endpoints ────────────────────────────────────────────────────────────

@app.post("/files", summary="Upload file (multipart) — auto replace runs immediately")
async def upload_file(file: UploadFile):
    src = await file.read()
    name = file.filename or "upload.bin"
    tokenized, n = _run_replace(name, src)
    return _store(name, tokenized, extra={"tokens_created": n})


class TextBody(BaseModel):
    name: str
    content: str


@app.post("/files/text", summary="Upload text content — auto replace runs immediately")
def upload_text(body: TextBody):
    tokenized, n = _run_replace(body.name, body.content.encode("utf-8"))
    return _store(body.name, tokenized, extra={"tokens_created": n})


@app.get("/files", summary="List stored (tokenised) files")
def list_files():
    out = []
    for d in sorted(STORAGE.iterdir()):
        m = d / "_meta.json"
        if m.exists():
            meta = json.loads(m.read_text())
            # Skip internal files
            if not meta["name"].startswith("_"):
                out.append(meta)
    return out


@app.get("/files/{file_id}", summary="Get tokenised file content")
def get_file(file_id: str):
    meta = _meta(file_id)
    fp = STORAGE / file_id / meta["name"]
    try:
        return PlainTextResponse(fp.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        raise HTTPException(422, "File is binary; cannot return as text")


@app.delete("/files/{file_id}", summary="Delete a stored file")
def delete_file(file_id: str):
    _meta(file_id)
    shutil.rmtree(STORAGE / file_id)
    return {"deleted": file_id}


# ── Restore endpoint ──────────────────────────────────────────────────────────

class RestoreBody(BaseModel):
    name: str
    content: str


@app.post("/restore", summary="Restore AI output: tokens → original values")
def do_restore(body: RestoreBody):
    """
    Pass the AI's response (containing [[KW_...]] tokens) here.
    Uses the global mapping built from all previous uploads.
    Restored file is saved separately and is NOT visible via GET /files.
    """
    restored = _run_restore(body.name, body.content)
    out_name  = f"restored_{body.name}"
    out_path  = RESTORED / out_name
    out_path.write_bytes(restored)
    return {"success": True, "name": out_name}


# ── Restored file access ─────────────────────────────────────────────────────

@app.get("/restored", summary="List restored files")
def list_restored():
    return [
        {"name": f.name, "size": f.stat().st_size}
        for f in sorted(RESTORED.iterdir()) if f.is_file()
    ]


@app.get("/restored/{name}", summary="Download a restored file")
def get_restored(name: str):
    fp = RESTORED / name
    if not fp.exists():
        raise HTTPException(404, f"{name!r} not found in restored")
    try:
        return PlainTextResponse(fp.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        raise HTTPException(422, "File is binary; cannot return as text")


@app.delete("/restored/{name}", summary="Delete a restored file")
def delete_restored(name: str):
    fp = RESTORED / name
    if not fp.exists():
        raise HTTPException(404, f"{name!r} not found in restored")
    fp.unlink()
    return {"deleted": name}


# ── Keywords management ───────────────────────────────────────────────────────

@app.get("/keywords", summary="Show current keywords.txt content")
def get_keywords():
    kw = _require_keywords()
    return PlainTextResponse(kw.read_text(encoding="utf-8"))


@app.put("/keywords", summary="Update keywords.txt")
def put_keywords(body: TextBody):
    KEYWORDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEYWORDS_FILE.write_text(body.content, encoding="utf-8")
    lines = [l for l in body.content.splitlines() if l.strip() and not l.startswith("#")]
    return {"keywords_count": len(lines)}


# ── Content analysis ──────────────────────────────────────────────────────────

class AnalyzeBody(BaseModel):
    name: str = "input"
    content: str


@app.post("/analyze", summary="Detect IPs, domains, and hashes in text")
def analyze(body: AnalyzeBody):
    items = _analyze_content(body.content)
    counts: dict[str, int] = {}
    for item in items:
        counts[item["type"]] = counts.get(item["type"], 0) + 1
    return {"items": items, "counts": counts, "total": len(items)}


class AppendKeywordsBody(BaseModel):
    keywords: list[str]


@app.post("/keywords/append", summary="Append keywords to keywords.txt (skip duplicates)")
def append_keywords(body: AppendKeywordsBody):
    KEYWORDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing_text = KEYWORDS_FILE.read_text(encoding="utf-8") if KEYWORDS_FILE.exists() else ""
    existing_set = {
        l.strip() for l in existing_text.splitlines()
        if l.strip() and not l.startswith("#")
    }
    new_kws = [k.strip() for k in body.keywords if k.strip() and k.strip() not in existing_set]
    if new_kws:
        with open(KEYWORDS_FILE, "a", encoding="utf-8") as f:
            if existing_text and not existing_text.endswith("\n"):
                f.write("\n")
            f.write("\n".join(new_kws) + "\n")
    return {
        "appended": len(new_kws),
        "skipped": len(body.keywords) - len(new_kws),
        "total": len(existing_set) + len(new_kws),
    }


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)
