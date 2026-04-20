"""
Tests for the MCP server HTTP API (mcp/server.py).

Uses FastAPI TestClient — no network required.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the FastAPI app from mcp/server.py
sys.path.insert(0, str(Path(__file__).parent.parent / "mcp"))

from fastapi.testclient import TestClient
from server import app, STORAGE

import shutil

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_storage(tmp_path, monkeypatch):
    """Redirect STORAGE to a fresh tmp directory for each test."""
    import server as srv
    fake_storage = tmp_path / "storage"
    fake_storage.mkdir()
    monkeypatch.setattr(srv, "STORAGE", fake_storage)
    yield
    # cleanup is handled by tmp_path fixture


# ── File management ───────────────────────────────────────────────────────────

class TestFileUpload:
    def test_upload_text_returns_file_id(self):
        r = client.post("/files/text", json={"name": "hello.txt", "content": "hello world"})
        assert r.status_code == 200
        data = r.json()
        assert "file_id" in data
        assert data["name"] == "hello.txt"
        assert data["size"] == len("hello world")

    def test_upload_multipart(self):
        r = client.post("/files", files={"file": ("doc.txt", b"content here", "text/plain")})
        assert r.status_code == 200
        assert r.json()["name"] == "doc.txt"

    def test_list_files_empty(self):
        assert client.get("/files").json() == []

    def test_list_files_after_upload(self):
        client.post("/files/text", json={"name": "a.txt", "content": "aaa"})
        client.post("/files/text", json={"name": "b.txt", "content": "bbb"})
        files = client.get("/files").json()
        assert len(files) == 2
        names = {f["name"] for f in files}
        assert names == {"a.txt", "b.txt"}

    def test_get_file_content(self):
        fid = client.post("/files/text", json={"name": "x.txt", "content": "xyz"}).json()["file_id"]
        r = client.get(f"/files/{fid}")
        assert r.status_code == 200
        assert r.text == "xyz"

    def test_get_file_not_found(self):
        assert client.get("/files/nonexistent-id").status_code == 404

    def test_delete_file(self):
        fid = client.post("/files/text", json={"name": "del.txt", "content": "bye"}).json()["file_id"]
        assert client.delete(f"/files/{fid}").status_code == 200
        assert client.get(f"/files/{fid}").status_code == 404

    def test_delete_nonexistent_returns_404(self):
        assert client.delete("/files/no-such-id").status_code == 404


# ── replace endpoint ──────────────────────────────────────────────────────────

class TestReplace:
    def _upload(self, name: str, content: str) -> str:
        return client.post("/files/text", json={"name": name, "content": content}).json()["file_id"]

    def test_replace_removes_keywords(self):
        fid = self._upload("doc.txt", "Contact: alice@corp.com / pass: Secret123")
        kfid = self._upload("keywords.txt", "alice@corp.com\nSecret123\n")

        r = client.post("/replace", json={"file_id": fid, "keywords_file_id": kfid})
        assert r.status_code == 200
        data = r.json()
        assert "tokenized_file_id" in data
        assert "mapping_file_id" in data
        assert data["tokens_created"] == 2

        tokenized = client.get(f"/files/{data['tokenized_file_id']}").text
        assert "alice@corp.com" not in tokenized
        assert "Secret123" not in tokenized
        assert "[[KW_" in tokenized

    def test_replace_mapping_has_all_keywords(self):
        fid = self._upload("doc.txt", "user: bob@example.com key: mykey")
        kfid = self._upload("kw.txt", "bob@example.com\nmykey\n")
        data = client.post("/replace", json={"file_id": fid, "keywords_file_id": kfid}).json()

        mapping_text = client.get(f"/files/{data['mapping_file_id']}").text
        mapping = json.loads(mapping_text)
        values = {v.lower() for v in mapping.values()}
        assert "bob@example.com" in values
        assert "mykey" in values

    def test_replace_no_keywords_in_file_returns_422(self):
        fid = self._upload("doc.txt", "nothing sensitive here")
        kfid = self._upload("kw.txt", "alice@corp.com\n")
        r = client.post("/replace", json={"file_id": fid, "keywords_file_id": kfid})
        assert r.status_code == 422

    def test_replace_unknown_file_id_returns_404(self):
        kfid = self._upload("kw.txt", "alice\n")
        r = client.post("/replace", json={"file_id": "bad-id", "keywords_file_id": kfid})
        assert r.status_code == 404


# ── restore endpoint ──────────────────────────────────────────────────────────

class TestRestore:
    def _upload(self, name: str, content: str) -> str:
        return client.post("/files/text", json={"name": name, "content": content}).json()["file_id"]

    def test_restore_recovers_original_values(self):
        fid = self._upload("doc.txt", "email: alice@corp.com  token: abc123")
        kfid = self._upload("kw.txt", "alice@corp.com\nabc123\n")

        rep = client.post("/replace", json={"file_id": fid, "keywords_file_id": kfid}).json()

        # Simulate AI output: AI returns the tokenised text unchanged
        tokenized_content = client.get(f"/files/{rep['tokenized_file_id']}").text
        ai_out_fid = self._upload("ai_output.txt", tokenized_content)

        res = client.post("/restore", json={
            "file_id":         ai_out_fid,
            "mapping_file_id": rep["mapping_file_id"],
        })
        assert res.status_code == 200
        restored_fid = res.json()["restored_file_id"]

        restored = client.get(f"/files/{restored_fid}").text
        assert "alice@corp.com" in restored
        assert "abc123" in restored
        assert "[[KW_" not in restored

    def test_restore_full_roundtrip(self):
        """replace → restore on original file must reproduce exact content."""
        original = "Project: Acme\nContact: bob@acme.com\nKey: sk-live-xyz"
        fid = self._upload("report.txt", original)
        kfid = self._upload("kw.txt", "bob@acme.com\nsk-live-xyz\nAcme\n")

        rep = client.post("/replace", json={"file_id": fid, "keywords_file_id": kfid}).json()
        res = client.post("/restore", json={
            "file_id":         rep["tokenized_file_id"],
            "mapping_file_id": rep["mapping_file_id"],
        }).json()

        restored = client.get(f"/files/{res['restored_file_id']}").text
        assert restored == original

    def test_restore_unknown_file_id_returns_404(self):
        mapping_fid = self._upload("mapping.json", json.dumps({"[[KW_AAAABBBB]]": "secret"}))
        r = client.post("/restore", json={"file_id": "bad-id", "mapping_file_id": mapping_fid})
        assert r.status_code == 404


# ── end-to-end ────────────────────────────────────────────────────────────────

class TestEndToEnd:
    def _upload(self, name: str, content: str) -> str:
        return client.post("/files/text", json={"name": name, "content": content}).json()["file_id"]

    def test_html_dashboard_workflow(self):
        """Simulate: upload CRM HTML + keywords → replace → AI passes through → restore."""
        html = (
            '<span id="user">alice@corp.com</span>\n'
            'const TOKEN = "eyJhbGci.secret2024";\n'
            'fetch("https://api.corp.internal/v2/customers");\n'
        )
        keywords = "alice@corp.com\neyJhbGci.secret2024\ncorp.internal\n"

        html_fid = self._upload("dashboard.html", html)
        kw_fid   = self._upload("keywords.txt", keywords)

        # Step 1: replace
        rep = client.post("/replace", json={"file_id": html_fid, "keywords_file_id": kw_fid}).json()
        tokenized = client.get(f"/files/{rep['tokenized_file_id']}").text
        assert "alice@corp.com" not in tokenized
        assert "corp.internal" not in tokenized
        assert "[[KW_" in tokenized

        # Step 2: simulate AI returning tokenised content with a wrapping test
        ai_response = (
            "await page.goto('https://api.[[KW_" +
            tokenized.split("[[KW_")[1].split("]]")[0] +
            "]]');\n" + tokenized
        )
        ai_fid = self._upload("ai_output.ts", ai_response)

        # Step 3: restore
        res = client.post("/restore", json={
            "file_id":         ai_fid,
            "mapping_file_id": rep["mapping_file_id"],
        }).json()
        final = client.get(f"/files/{res['restored_file_id']}").text

        assert "alice@corp.com" in final
        assert "corp.internal" in final
        assert "[[KW_" not in final
