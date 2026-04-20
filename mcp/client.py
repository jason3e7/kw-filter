"""
kw-filter MCP Client (stdio server for Claude Code)
====================================================
An MCP server that runs as a subprocess under Claude Code and proxies
kw-filter operations to the HTTP web server (server.py).

Claude Code config  (~/.claude.json  or project .claude/settings.json):

    {
      "mcpServers": {
        "kw-filter": {
          "command": "python3",
          "args": ["/path/to/kw-filter/mcp/client.py"],
          "env": { "KW_SERVER_URL": "http://localhost:8000" }
        }
      }
    }

Environment:
    KW_SERVER_URL   URL of the running server.py   (default: http://localhost:8000)
"""
from __future__ import annotations

import os
import httpx
from mcp.server.fastmcp import FastMCP

SERVER_URL = os.environ.get("KW_SERVER_URL", "http://localhost:8000").rstrip("/")

mcp = FastMCP(
    "kw-filter",
    description=(
        "Filter sensitive keywords from files before sending to AI, "
        "then restore originals afterwards."
    ),
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get(path: str) -> httpx.Response:
    r = httpx.get(f"{SERVER_URL}{path}", timeout=30)
    r.raise_for_status()
    return r


def _post(path: str, payload: dict) -> httpx.Response:
    r = httpx.post(f"{SERVER_URL}{path}", json=payload, timeout=60)
    r.raise_for_status()
    return r


def _del(path: str) -> httpx.Response:
    r = httpx.delete(f"{SERVER_URL}{path}", timeout=30)
    r.raise_for_status()
    return r


# ── File management tools ─────────────────────────────────────────────────────

@mcp.tool()
def upload_file(name: str, content: str) -> str:
    """Upload a text file to the kw-filter server.

    Args:
        name:    filename including extension, e.g. "report.txt" or "keywords.txt"
        content: full text content of the file

    Returns:
        file_id — pass this to replace(), restore(), or get_file()
    """
    return _post("/files/text", {"name": name, "content": content}).json()["file_id"]


@mcp.tool()
def list_files() -> list[dict]:
    """List all files currently stored on the kw-filter server.

    Returns a list of {file_id, name, size} dicts.
    """
    return _get("/files").json()


@mcp.tool()
def get_file(file_id: str) -> str:
    """Retrieve the text content of a stored file.

    Args:
        file_id: ID returned by upload_file() or replace()/restore()
    """
    return _get(f"/files/{file_id}").text


@mcp.tool()
def delete_file(file_id: str) -> str:
    """Delete a file from the server.

    Args:
        file_id: ID of the file to delete
    """
    _del(f"/files/{file_id}")
    return f"Deleted {file_id}"


# ── kw-filter operation tools ─────────────────────────────────────────────────

@mcp.tool()
def replace(file_id: str, keywords_file_id: str) -> dict:
    """Replace sensitive keywords in a file with anonymous [[KW_XXXXXXXX]] tokens.

    Typical workflow:
      1. Upload the file you want to sanitise → file_id
      2. Upload a keywords.txt listing one sensitive value per line → keywords_file_id
      3. Call replace(file_id, keywords_file_id)
      4. Send the tokenised file content to an AI model
      5. Call restore() on the AI's response to get real values back

    Args:
        file_id:          ID of the file to tokenise
        keywords_file_id: ID of the keywords.txt file

    Returns:
        {
          "tokenized_file_id": "...",   ← share this with the AI
          "mapping_file_id":   "...",   ← keep this to restore later
          "tokens_created":    N
        }
    """
    return _post("/replace", {
        "file_id":          file_id,
        "keywords_file_id": keywords_file_id,
    }).json()


@mcp.tool()
def restore(file_id: str, mapping_file_id: str) -> str:
    """Restore original values in a file that contains [[KW_XXXXXXXX]] tokens.

    Use this on the AI's output after it has processed a tokenised file.

    Args:
        file_id:          ID of the tokenised file (e.g. AI-generated output)
        mapping_file_id:  ID of the mapping.json produced by replace()

    Returns:
        file_id of the restored file — call get_file() to read its content
    """
    return _post("/restore", {
        "file_id":         file_id,
        "mapping_file_id": mapping_file_id,
    }).json()["restored_file_id"]


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
