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
import json
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
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

app = FastAPI(
    title="kw-filter Server",
    description=(
        "Upload files → auto replace with keywords.txt. "
        "GET /files/{id} → tokenised content safe to send to AI. "
        "POST /restore → AI output restored to original values."
    ),
    version="2.0.0",
)


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


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)
