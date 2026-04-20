# kw-filter MCP Integration

## Architecture

```
Browser / curl  ──POST /files──────────────────────────┐
                                                        ▼
Claude Code ──stdio──► client.py ──HTTP──► server.py :8000
                                               │
                                    auto replace on upload
                                    auto restore on /restore
```

| File | Role |
|---|---|
| `server.py` | FastAPI — auto replace on upload, auto restore endpoint |
| `client.py` | MCP stdio server — 3 tools for Claude Code |
| `keywords.txt` | One sensitive value per line (**create this first**) |

## Setup

```bash
pip install -r mcp/requirements.txt

# Create your keywords file
cat > mcp/keywords.txt << 'EOF'
alice@corp.com
Secret123
acme-internal.com
sk-live-abc123
EOF

# Start the server
python mcp/server.py
```

Override keywords path: `KW_KEYWORDS_FILE=/other/path/keywords.txt python mcp/server.py`

Interactive API docs → http://localhost:8000/docs

---

## Using with curl

```bash
# Upload a file — replace runs automatically
curl -F "file=@report.txt" http://localhost:8000/files
# → {"file_id": "abc-123", "name": "report.txt", "tokens_created": 4}

# List files
curl http://localhost:8000/files

# Get tokenised content (safe to send to AI)
curl http://localhost:8000/files/abc-123

# After AI returns output with [[KW_...]] tokens, restore it
curl -X POST http://localhost:8000/restore \
  -H "Content-Type: application/json" \
  -d '{"name": "ai_output.txt", "content": "...AI response with [[KW_...]] tokens..."}'
# → {"file_id": "...", "name": "restored_ai_output.txt", "content": "...original values..."}

# View / update keywords
curl http://localhost:8000/keywords
curl -X PUT http://localhost:8000/keywords \
  -H "Content-Type: application/json" \
  -d '{"name": "kw", "content": "new_keyword_1\nnew_keyword_2\n"}'
```

---

## Using with Claude Code (MCP)

**Step 1** — add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "kw-filter": {
      "command": "python3",
      "args": ["/absolute/path/to/kw-filter/mcp/client.py"],
      "env": { "KW_SERVER_URL": "http://localhost:8000" }
    }
  }
}
```

**Step 2** — start the server, restart Claude Code, then run `/mcp` to confirm.

**Step 3** — 3 tools are available:

| Tool | What it does |
|---|---|
| `list_files()` | List all uploaded (auto-tokenised) files |
| `get_files(file_id)` | Get tokenised content — safe to paste into any prompt |
| `upload_files(name, content)` | Give it AI output with tokens → get back restored content |

### Example conversation

```
You: I uploaded dashboard.html to the server. Please read it and write
     a Playwright test that checks the customer list renders correctly.

Claude: [list_files() → finds dashboard.html with file_id abc-123]
        [get_files("abc-123") → reads tokenised HTML]
        Here is the Playwright test:

        test('customer list', async ({ page }) => {
          await page.goto('https://crm.[[KW_A1B2]]/dashboard');
          await expect(page.locator('#user')).toHaveText('[[KW_C3D4]]');
          ...
        });

You: Now restore the real values.

Claude: [upload_files("test.ts", "<the test above>")]
        → returns test with acme-corp.internal, alice@corp.com etc. restored
```

---

## Running tests

```bash
python3 -m pytest tests/test_mcp_server.py -v   # 20 tests
python3 -m pytest tests/ -v                      # all tests
```
