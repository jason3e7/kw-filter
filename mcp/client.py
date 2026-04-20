"""
kw-filter MCP Client (stdio server for Claude Code)
====================================================
Three tools:
  list_files    — list tokenised files available on the server
  get_files     — download auto-replaced file to local filesystem + return content
  upload_files  — send AI output to server for restore, save result locally

Files are written to KW_WORK_DIR (default: current working directory).

Claude Code config  (~/.claude.json  or  .claude/settings.json):

    {
      "mcpServers": {
        "kw-filter": {
          "command": "python3",
          "args": ["/path/to/kw-filter/mcp/client.py"],
          "env": {
            "KW_SERVER_URL": "http://localhost:8000",
            "KW_WORK_DIR":   "/path/to/your/project"
          }
        }
      }
    }

Environment:
    KW_SERVER_URL   URL of the running server.py  (default: http://localhost:8000)
    KW_WORK_DIR     Directory where local files are read/written (default: cwd)
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

SERVER_URL = os.environ.get("KW_SERVER_URL", "http://localhost:8000").rstrip("/")
WORK_DIR   = Path(os.environ.get("KW_WORK_DIR", Path.cwd())).expanduser().resolve()

mcp = FastMCP("kw-filter")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get(path: str) -> httpx.Response:
    r = httpx.get(f"{SERVER_URL}{path}", timeout=30)
    r.raise_for_status()
    return r


def _post(path: str, payload: dict) -> httpx.Response:
    r = httpx.post(f"{SERVER_URL}{path}", json=payload, timeout=60)
    r.raise_for_status()
    return r


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def list_files() -> list[dict]:
    """List all files stored on the kw-filter server.

    Each entry has already been processed — sensitive values are replaced with
    [[KW_...]] tokens.  Use get_files() to download and read one.

    Returns a list of {file_id, name, size, tokens_created}.
    """
    return _get("/files").json()


@mcp.tool()
def get_files(file_id: str) -> str:
    """Download the tokenised version of a file to the local filesystem.

    The file contains [[KW_...]] tokens in place of sensitive values — safe
    to include in any AI prompt.  A local copy is written so you can also
    inspect or edit it outside this conversation.

    Args:
        file_id: ID from list_files()

    Returns:
        Local file path + full tokenised content.
    """
    # Resolve original filename from the file listing
    files = _get("/files").json()
    meta  = next((f for f in files if f["file_id"] == file_id), None)
    if meta is None:
        raise ValueError(f"file_id {file_id!r} not found on server")

    content   = _get(f"/files/{file_id}").text
    local_path = WORK_DIR / f"tokenized_{meta['name']}"
    local_path.write_text(content, encoding="utf-8")

    return (
        f"Tokenised file saved to: {local_path}\n"
        f"Tokens: {meta.get('tokens_created', '?')}\n"
        f"\n{content}"
    )


@mcp.tool()
def upload_files(name: str, content: str) -> str:
    """Send AI-generated content to the server for restore, save result locally.

    Use this after the AI has produced output containing [[KW_...]] tokens.
    The server substitutes every token with its original value, and the
    restored file is written to your local KW_WORK_DIR.

    Args:
        name:    filename for the restored output, e.g. "playwright_test.ts"
        content: AI response text that contains [[KW_...]] tokens

    Returns:
        Local file path of the restored file + its full content.
    """
    data = _post("/restore", {"name": name, "content": content}).json()

    restored_content = data["content"]
    local_path = WORK_DIR / data["name"]
    local_path.write_text(restored_content, encoding="utf-8")

    return (
        f"Restored file saved to: {local_path}\n"
        f"\n{restored_content}"
    )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
