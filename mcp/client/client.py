"""
kw-filter MCP Client (stdio server for Claude Code)
====================================================
Three tools:
  list_files    — list tokenised files available on the server
  get_files     — get auto-replaced (tokenised) content, safe to send to AI
  upload_files  — upload AI output, auto-restored and saved on the server

Claude Code config  (~/.claude.json  or  .claude/settings.json):

    {
      "mcpServers": {
        "kw-filter": {
          "command": "python3",
          "args": ["/path/to/kw-filter/mcp/client/client.py"],
          "env": { "KW_SERVER_URL": "http://localhost:8000" }
        }
      }
    }

Environment:
    KW_SERVER_URL   URL of the running server.py  (default: http://localhost:8000)
"""
from __future__ import annotations

import os
import httpx
from mcp.server.fastmcp import FastMCP

SERVER_URL = os.environ.get("KW_SERVER_URL", "http://localhost:8000").rstrip("/")

mcp = FastMCP("kw-filter")


def _get(path: str) -> httpx.Response:
    r = httpx.get(f"{SERVER_URL}{path}", timeout=30)
    r.raise_for_status()
    return r


def _post(path: str, payload: dict) -> httpx.Response:
    r = httpx.post(f"{SERVER_URL}{path}", json=payload, timeout=60)
    r.raise_for_status()
    return r


@mcp.tool()
def list_files() -> list[dict]:
    """List all files stored on the kw-filter server.

    Each file has already been processed — sensitive values are replaced with
    [[KW_...]] tokens.  Use get_files() to read the content.

    Returns a list of {file_id, name, size, tokens_created}.
    """
    return _get("/files").json()


@mcp.tool()
def get_files(file_id: str) -> str:
    """Get the tokenised content of a stored file.

    The content has had all sensitive keywords replaced with [[KW_...]] tokens,
    so it is safe to include in prompts or send to any AI service.

    Args:
        file_id: ID from list_files()

    Returns:
        Tokenised file content.
    """
    return _get(f"/files/{file_id}").text


@mcp.tool()
def upload_files(name: str, content: str) -> str:
    """Upload AI-generated content and restore original values automatically.

    Use this after the AI has produced output that contains [[KW_...]] tokens.
    The server replaces every token with its original value and saves the
    result separately.

    Args:
        name:    filename for the restored output, e.g. "playwright_test.ts"
        content: AI response text that contains [[KW_...]] tokens

    Returns:
        Success message and restored filename.
    """
    data = _post("/restore", {"name": name, "content": content}).json()
    return f"Restored successfully → {data['name']}"


if __name__ == "__main__":
    mcp.run()
