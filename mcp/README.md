# kw-filter MCP Integration

Two components:

| File | Role |
|---|---|
| `server.py` | FastAPI HTTP server — file storage + replace/restore REST API |
| `client.py` | MCP stdio server — Claude Code connects here, proxies to `server.py` |

```
Browser / curl ──POST /files──────────────────────────┐
                                                       ▼
Claude Code ──stdio──► client.py ──HTTP──► server.py :8000
                                               │
                                          kw_tools.py
```

## Setup

```bash
pip install -r mcp/requirements.txt
```

## 1 — Start the web server

```bash
python mcp/server.py              # listens on 0.0.0.0:8000
python mcp/server.py --port 9000  # custom port
```

Interactive API docs: http://localhost:8000/docs

## 2 — Upload files (browser / curl)

```bash
# Upload a file to process
curl -F "file=@report.txt" http://localhost:8000/files
# → {"file_id": "abc-123", "name": "report.txt", "size": 4200}

# Upload keywords list
curl -F "file=@keywords.txt" http://localhost:8000/files
# → {"file_id": "def-456", ...}
```

## 3 — Configure Claude Code

Add to `~/.claude.json` (global) or `.claude/settings.json` (project):

```json
{
  "mcpServers": {
    "kw-filter": {
      "command": "python3",
      "args": ["/absolute/path/to/kw-filter/mcp/client.py"],
      "env": {
        "KW_SERVER_URL": "http://localhost:8000"
      }
    }
  }
}
```

Then restart Claude Code. The following tools become available:

| Tool | Description |
|---|---|
| `upload_file(name, content)` | Upload text file, returns `file_id` |
| `list_files()` | List all stored files |
| `get_file(file_id)` | Read file content |
| `delete_file(file_id)` | Remove a file |
| `replace(file_id, keywords_file_id)` | Tokenise sensitive values |
| `restore(file_id, mapping_file_id)` | Restore original values |

## Typical Claude Code workflow

```
You: I uploaded report.txt (id: abc-123) and keywords.txt (id: def-456).
     Please tokenise it, then summarise the content.

Claude: [calls replace("abc-123", "def-456")]
        → tokenized_file_id: "ghi-789", mapping_file_id: "jkl-012"
        [calls get_file("ghi-789")]
        → reads tokenised content, summarises it

You: Now restore the original values in your summary.

Claude: [calls upload_file("summary.txt", <summary text>)]
        → file_id: "mno-345"
        [calls restore("mno-345", "jkl-012")]
        → restored_file_id: "pqr-678"
        [calls get_file("pqr-678")]
        → returns summary with real names/emails back
```

## Running tests

```bash
python3 -m pytest tests/test_mcp_server.py -v
```
