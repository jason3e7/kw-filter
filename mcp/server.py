"""
kw-filter MCP Web Server
========================
FastAPI HTTP server that stores files and exposes kw-filter replace/restore
operations as REST endpoints.

Run:
    pip install -r mcp/requirements.txt
    python mcp/server.py                    # default: 0.0.0.0:8000
    python mcp/server.py --port 9000
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
import uvicorn

from kw_tools import cmd_replace, cmd_restore  # noqa: E402

# ── Storage ───────────────────────────────────────────────────────────────────

STORAGE = Path(__file__).parent / "storage"
STORAGE.mkdir(exist_ok=True)


def _meta(file_id: str) -> dict:
    d = STORAGE / file_id
    if not d.exists():
        raise HTTPException(404, f"file_id {file_id!r} not found")
    return json.loads((d / "_meta.json").read_text())


def _path(file_id: str) -> Path:
    m = _meta(file_id)
    return STORAGE / file_id / m["name"]


def _store(name: str, content: bytes) -> dict:
    file_id = str(uuid.uuid4())
    d = STORAGE / file_id
    d.mkdir()
    (d / name).write_bytes(content)
    meta = {"file_id": file_id, "name": name, "size": len(content)}
    (d / "_meta.json").write_text(json.dumps(meta))
    return meta


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="kw-filter Server",
    description="File storage + kw-filter replace/restore API",
    version="1.0.0",
)


# ── File endpoints ────────────────────────────────────────────────────────────

@app.post("/files", summary="Upload file (multipart — for browser / curl)")
async def upload_file(file: UploadFile):
    content = await file.read()
    return _store(file.filename or "upload.bin", content)


class TextBody(BaseModel):
    name: str
    content: str


@app.post("/files/text", summary="Upload text content as a named file")
def upload_text(body: TextBody):
    return _store(body.name, body.content.encode("utf-8"))


@app.get("/files", summary="List all stored files")
def list_files():
    out = []
    for d in sorted(STORAGE.iterdir()):
        m = d / "_meta.json"
        if m.exists():
            out.append(json.loads(m.read_text()))
    return out


@app.get("/files/{file_id}", summary="Get file content as text")
def get_file(file_id: str):
    fp = _path(file_id)
    try:
        return PlainTextResponse(fp.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        raise HTTPException(422, "File is binary; cannot return as text")


@app.delete("/files/{file_id}", summary="Delete a stored file")
def delete_file(file_id: str):
    _meta(file_id)   # raises 404 if missing
    shutil.rmtree(STORAGE / file_id)
    return {"deleted": file_id}


# ── kw-filter operations ──────────────────────────────────────────────────────

class ReplaceRequest(BaseModel):
    file_id: str
    keywords_file_id: str


class RestoreRequest(BaseModel):
    file_id: str
    mapping_file_id: str


@app.post("/replace", summary="Replace sensitive keywords with tokens")
def do_replace(body: ReplaceRequest):
    """
    Run kw-filter replace on a stored file.

    - **file_id**: ID of the file to tokenise
    - **keywords_file_id**: ID of the keywords.txt file

    Returns `tokenized_file_id` and `mapping_file_id`.
    The mapping is needed later by `/restore`.
    """
    src = _path(body.file_id)
    kw_path = _path(body.keywords_file_id)
    src_meta = _meta(body.file_id)

    with tempfile.TemporaryDirectory() as _tmp:
        tmp = Path(_tmp)
        target = tmp / src_meta["name"]
        shutil.copy(src, target)
        mapping_file = tmp / "mapping.json"

        ns = argparse.Namespace(
            keywords=str(kw_path),
            target=str(target),
            mapping=str(mapping_file),
            backup=False,
            dry_run=False,
        )
        cmd_replace(ns)

        if not mapping_file.exists():
            raise HTTPException(422, "replace produced no mapping — no keywords found in file")

        if not mapping_file.exists():
            raise HTTPException(422, "replace produced no output — no keywords found in file")
        mapping_content = mapping_file.read_bytes()
        tokens_created = len(json.loads(mapping_content))
        if tokens_created == 0:
            raise HTTPException(422, "no keywords matched — check your keywords.txt")

        tok_meta = _store(f"tokenized_{src_meta['name']}", target.read_bytes())
        map_meta = _store("mapping.json", mapping_content)

    return {
        "tokenized_file_id": tok_meta["file_id"],
        "mapping_file_id":   map_meta["file_id"],
        "tokens_created":    tokens_created,
    }


@app.post("/restore", summary="Restore original values from tokens")
def do_restore(body: RestoreRequest):
    """
    Run kw-filter restore on a tokenised file.

    - **file_id**: ID of the tokenised file (e.g. AI-generated output)
    - **mapping_file_id**: ID of the mapping.json produced by `/replace`

    Returns `restored_file_id`.
    """
    src = _path(body.file_id)
    mapping_src = _path(body.mapping_file_id)
    src_meta = _meta(body.file_id)

    with tempfile.TemporaryDirectory() as _tmp:
        tmp = Path(_tmp)
        target = tmp / src_meta["name"]
        shutil.copy(src, target)
        mapping_file = tmp / "mapping.json"
        shutil.copy(mapping_src, mapping_file)

        ns = argparse.Namespace(
            mapping=str(mapping_file),
            target=str(target),
            backup=False,
            dry_run=False,
        )
        cmd_restore(ns)

        restored_meta = _store(f"restored_{src_meta['name']}", target.read_bytes())

    return {"restored_file_id": restored_meta["file_id"]}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)
