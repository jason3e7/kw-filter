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

from kw_tools import cmd_replace, cmd_restore, load_keywords, sorted_keywords  # noqa: E402

# ── Paths ─────────────────────────────────────────────────────────────────────

MCP_DIR      = Path(__file__).parent
STORAGE      = MCP_DIR / "storage"
RESTORED     = MCP_DIR / "restored"
MAPPING_FILE = STORAGE / "_mapping.json"
CONFIG_FILE  = MCP_DIR / "config.json"

STORAGE.mkdir(exist_ok=True)
RESTORED.mkdir(exist_ok=True)

# ── Config ────────────────────────────────────────────────────────────────────

_CONFIG_DEFAULTS: dict = {
    "keywords_file":          "keywords.txt",
    # hf_hub_offline: load ai4privacy model from local cache (no network)
    "hf_hub_offline":         True,
    # ai4privacy_chunk_chars: chars per chunk sent to the PII model (max ~1536 tokens)
    # Dense content (logs, code) can be ~1 char/token; 1200 chars ≈ 1200 tokens worst case
    "ai4privacy_chunk_chars": 1200,
    # ai4privacy_max_chars: total chars fed to ai4privacy; content beyond this is ignored
    # Prevents server hang on large files (1264 chunks × inference time = hours)
    # Increase if your hardware is fast enough; set to 0 to disable the limit
    "ai4privacy_max_chars":   60000,
    # ip_blacklist: list of IPs blocked from /docs /keywords /restored
    "ip_blacklist":           [],
    # llm_url / llm_model: reserved for future local LLM keyword extraction (Ollama etc.)
    # Leave llm_url empty to disable; currently has no effect
    "llm_url":                "",
    "llm_model":              "llama3",
}


def _load_config() -> dict:
    cfg = dict(_CONFIG_DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"[kw-filter] config.json load error: {e} — using defaults", flush=True)
    else:
        # Write defaults so the user can see and edit the file
        CONFIG_FILE.write_text(
            json.dumps(_CONFIG_DEFAULTS, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"[kw-filter] config.json not found — created with defaults at {CONFIG_FILE}", flush=True)
    return cfg


def _save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


_CFG = _load_config()


def _resolve_path(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else MCP_DIR / path


KEYWORDS_FILE = _resolve_path(_CFG["keywords_file"])

# ── LLM integration (optional) ────────────────────────────────────────────────
LLM_URL   = _CFG["llm_url"]
LLM_MODEL = _CFG["llm_model"]

# ── ai4privacy (optional) ─────────────────────────────────────────────────────
if _CFG["hf_hub_offline"]:
    os.environ["HF_HUB_OFFLINE"] = "1"
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


_AI4PRIVACY_CHUNK_CHARS: int = int(_CFG["ai4privacy_chunk_chars"])
_AI4PRIVACY_MAX_CHARS:   int = int(_CFG["ai4privacy_max_chars"])


def _split_text_chunks(text: str, max_chars: int) -> list[str]:
    """Split text into chunks ≤ max_chars, breaking at newline or word boundaries."""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= max_chars:
            chunks.append(text)
            break
        pos = text.rfind('\n', 0, max_chars)
        if pos < max_chars // 2:
            pos = text.rfind(' ', 0, max_chars)
        if pos <= 0:
            pos = max_chars
        chunks.append(text[:pos])
        text = text[pos:].lstrip('\n')
    return [c for c in chunks if c.strip()]


def _analyze_with_ai4privacy(content: str) -> list[dict]:
    """Extract PII using ai4privacy, chunking large inputs automatically.

    Total input is capped at ai4privacy_max_chars (config.json) to prevent
    server hang on large files. Set to 0 to disable the cap.
    """
    if _ai4privacy_protect is None:
        return [], []

    warnings: list[str] = []
    total = len(content)
    if _AI4PRIVACY_MAX_CHARS > 0 and total > _AI4PRIVACY_MAX_CHARS:
        msg = (
            f"ai4privacy: 內容 {total:,} 字元超過上限 {_AI4PRIVACY_MAX_CHARS:,}，"
            f"僅分析前 {_AI4PRIVACY_MAX_CHARS:,} 字元（可在 config.json 調整 ai4privacy_max_chars）"
        )
        print(f"[kw-filter] {msg}", flush=True)
        warnings.append(msg)
        content = content[:_AI4PRIVACY_MAX_CHARS]

    chunks = _split_text_chunks(content, _AI4PRIVACY_CHUNK_CHARS)
    n = len(chunks)
    print(f"[kw-filter] ai4privacy: {len(content)} chars → {n} chunks", flush=True)

    agg: dict[str, dict[str, int]] = {}
    for i, chunk in enumerate(chunks):
        try:
            result = _ai4privacy_protect(chunk, classify_pii=True, verbose=True)
            for r in result.get("replacements", []):
                v = r.get("value", "").strip()
                label = r.get("label", "PII")
                if not v:
                    continue
                agg.setdefault(v, {})
                agg[v][label] = agg[v].get(label, 0) + 1
            print(f"[kw-filter] ai4privacy chunk {i + 1}/{n} done", flush=True)
        except Exception as e:
            print(f"[kw-filter] ai4privacy chunk {i + 1}/{n} error: {e}", flush=True)

    return [{"value": v, "labels": lc} for v, lc in agg.items()], warnings


def _analyze_content(content: str) -> tuple[list[dict], list[str]]:
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
    pii_items, warnings = _analyze_with_ai4privacy(content)
    for pii in pii_items:
        v = pii["value"]
        if v.lower() in seen_lower:
            continue
        seen.add(v); seen_lower.add(v.lower())
        labels: dict[str, int] = pii["labels"]
        primary = max(labels, key=labels.__getitem__) if labels else "PII"
        items.append({"value": v, "type": "PII", "subtype": primary,
                      "labels": labels, "auto_select": False})

    return items, warnings


# ── IP blacklist ──────────────────────────────────────────────────────────────
_RESTRICTED = ("/docs", "/openapi.json", "/redoc", "/keywords", "/restored")


def _load_blacklist() -> set[str]:
    """Re-reads config.json each call so edits take effect without restart."""
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        entries = cfg.get("ip_blacklist", [])
    except Exception:
        entries = _CFG.get("ip_blacklist", [])
    return {e.strip() for e in entries if isinstance(e, str) and e.strip()}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_pattern(keywords: list[str], regex_mode: bool) -> re.Pattern:
    """Compile keywords into a pattern; raises HTTP 422 on invalid regex."""
    parts = ([f"(?:{kw})" for kw in sorted_keywords(keywords)]
             if regex_mode else
             [re.escape(kw) for kw in sorted_keywords(keywords)])
    try:
        return re.compile("|".join(parts), re.IGNORECASE)
    except re.error as e:
        raise HTTPException(422, f"invalid regex pattern: {e}")


def _require_keywords() -> Path:
    if not KEYWORDS_FILE.exists():
        raise HTTPException(
            503,
            f"keywords.txt not found at {KEYWORDS_FILE}. "
            "Create mcp/server/keywords.txt or set keywords_file in config.json."
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


def _run_replace(src_name: str, src_bytes: bytes, regex: bool = False) -> tuple[bytes, int]:
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
            regex=regex,
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
async def upload_file(file: UploadFile, regex: bool = False):
    src = await file.read()
    name = file.filename or "upload.bin"
    tokenized, n = _run_replace(name, src, regex)
    return _store(name, tokenized, extra={"tokens_created": n})


class TextBody(BaseModel):
    name: str
    content: str
    regex: bool = False


@app.post("/files/text", summary="Upload text content — auto replace runs immediately")
def upload_text(body: TextBody):
    tokenized, n = _run_replace(body.name, body.content.encode("utf-8"), body.regex)
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
    items, warnings = _analyze_content(body.content)
    counts: dict[str, int] = {}
    for item in items:
        counts[item["type"]] = counts.get(item["type"], 0) + 1
    return {"items": items, "counts": counts, "total": len(items), "warnings": warnings}


class SearchBody(BaseModel):
    content: str
    regex: bool = False


@app.post("/search", summary="Search keywords in text — returns line/col matches")
def search_content(body: SearchBody):
    kw = _require_keywords()
    keywords = load_keywords(str(kw))
    pattern = _build_pattern(keywords, body.regex)
    matches = []
    for lineno, line in enumerate(body.content.splitlines(), 1):
        for m in pattern.finditer(line):
            matches.append({
                "line": lineno, "col": m.start() + 1,
                "keyword": m.group(0), "context": line.rstrip(),
            })
    return {"matches": matches, "total": len(matches)}


class ClearBody(BaseModel):
    content: str
    replacement: str = ""
    regex: bool = False


@app.post("/clear", summary="Remove keywords from text — returns cleaned content")
def clear_content(body: ClearBody):
    kw = _require_keywords()
    keywords = load_keywords(str(kw))
    pattern = _build_pattern(keywords, body.regex)
    result, count = pattern.subn(body.replacement, body.content)
    return {"content": result, "count": count}


class CleanlogBody(BaseModel):
    content: str
    regex: bool = False


@app.post("/cleanlog", summary="Drop lines containing keywords — returns filtered content")
def cleanlog_content(body: CleanlogBody):
    kw = _require_keywords()
    keywords = load_keywords(str(kw))
    pattern = _build_pattern(keywords, body.regex)
    lines = body.content.splitlines(keepends=True)
    kept = [l for l in lines if not pattern.search(l)]
    removed = len(lines) - len(kept)
    return {"content": "".join(kept), "removed": removed, "kept": len(kept)}


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
