"""
Tests for the redesigned MCP server (mcp/server/server.py).

Design:
  - Upload → auto replace using default keywords.txt
  - GET /files/{id} → tokenised content
  - POST /restore   → AI output restored to original values
  - Global mapping accumulates across multiple uploads
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "mcp" / "server"))

from fastapi.testclient import TestClient
import server as srv
from server import app

client = TestClient(app)

KEYWORDS = "alice@corp.com\nSecret123\nacme-internal\n"


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Each test gets clean storage/restored dirs, a temp keywords.txt, and a fresh mapping."""
    fake_storage  = tmp_path / "storage";  fake_storage.mkdir()
    fake_restored = tmp_path / "restored"; fake_restored.mkdir()
    kw_file = tmp_path / "keywords.txt"
    kw_file.write_text(KEYWORDS)

    monkeypatch.setattr(srv, "STORAGE",       fake_storage)
    monkeypatch.setattr(srv, "RESTORED",      fake_restored)
    monkeypatch.setattr(srv, "MAPPING_FILE",  fake_storage / "_mapping.json")
    monkeypatch.setattr(srv, "KEYWORDS_FILE", kw_file)
    yield


# ── Keywords endpoint ─────────────────────────────────────────────────────────

class TestKeywords:
    def test_get_keywords(self):
        r = client.get("/keywords")
        assert r.status_code == 200
        assert "alice@corp.com" in r.text

    def test_put_keywords(self):
        r = client.put("/keywords", json={"name": "kw", "content": "newkw1\nnewkw2\n"})
        assert r.status_code == 200
        assert r.json()["keywords_count"] == 2

    def test_get_keywords_missing_returns_503(self, monkeypatch, tmp_path):
        monkeypatch.setattr(srv, "KEYWORDS_FILE", tmp_path / "nonexistent.txt")
        assert client.get("/keywords").status_code == 503


# ── Upload (auto replace) ─────────────────────────────────────────────────────

class TestUpload:
    def test_upload_text_returns_meta(self):
        r = client.post("/files/text", json={"name": "doc.txt",
                                              "content": "email: alice@corp.com"})
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "doc.txt"
        assert data["tokens_created"] == 1
        assert "file_id" in data

    def test_upload_replaces_keywords_automatically(self):
        r = client.post("/files/text", json={"name": "doc.txt",
                                              "content": "user alice@corp.com pass Secret123"})
        fid = r.json()["file_id"]
        content = client.get(f"/files/{fid}").text
        assert "alice@corp.com" not in content
        assert "Secret123" not in content
        assert "[[KW_" in content

    def test_upload_multipart(self):
        r = client.post("/files", files={"file": ("f.txt", b"alice@corp.com", "text/plain")})
        assert r.status_code == 200
        assert r.json()["tokens_created"] == 1

    def test_upload_no_keyword_match_returns_422(self):
        r = client.post("/files/text", json={"name": "safe.txt",
                                              "content": "nothing sensitive here"})
        assert r.status_code == 422

    def test_upload_missing_keywords_file_returns_503(self, monkeypatch, tmp_path):
        monkeypatch.setattr(srv, "KEYWORDS_FILE", tmp_path / "missing.txt")
        r = client.post("/files/text", json={"name": "a.txt", "content": "alice@corp.com"})
        assert r.status_code == 503


# ── list / get / delete ───────────────────────────────────────────────────────

class TestFileManagement:
    def _upload(self, content: str, name="doc.txt") -> str:
        return client.post("/files/text", json={"name": name, "content": content}).json()["file_id"]

    def test_list_files_empty(self):
        assert client.get("/files").json() == []

    def test_list_files_shows_uploaded(self):
        self._upload("alice@corp.com info", "a.txt")
        self._upload("Secret123 stuff", "b.txt")
        files = client.get("/files").json()
        assert len(files) == 2
        assert {f["name"] for f in files} == {"a.txt", "b.txt"}

    def test_get_file_returns_tokenised_content(self):
        fid = self._upload("contact: alice@corp.com")
        text = client.get(f"/files/{fid}").text
        assert "alice@corp.com" not in text
        assert "[[KW_" in text

    def test_get_file_not_found(self):
        assert client.get("/files/bad-id").status_code == 404

    def test_delete_file(self):
        fid = self._upload("alice@corp.com")
        assert client.delete(f"/files/{fid}").status_code == 200
        assert client.get(f"/files/{fid}").status_code == 404

    def test_delete_nonexistent(self):
        assert client.delete("/files/no-such-id").status_code == 404


# ── Restore ───────────────────────────────────────────────────────────────────

class TestRestore:
    def _upload_and_get_tokenised(self, content: str, name="doc.txt") -> tuple[str, str]:
        fid = client.post("/files/text", json={"name": name, "content": content}).json()["file_id"]
        return fid, client.get(f"/files/{fid}").text

    def test_restore_returns_success_and_name_only(self):
        """Response must NOT contain file content."""
        _, tokenised = self._upload_and_get_tokenised("contact: alice@corp.com")
        data = client.post("/restore", json={"name": "out.txt", "content": tokenised}).json()
        assert data["success"] is True
        assert "restored_out.txt" == data["name"]
        assert "content" not in data

    def test_restore_saves_to_restored_dir(self, monkeypatch):
        """Restored file must land in RESTORED, not STORAGE."""
        import server as srv
        _, tokenised = self._upload_and_get_tokenised("pass: Secret123")
        client.post("/restore", json={"name": "out.txt", "content": tokenised})
        restored_file = srv.RESTORED / "restored_out.txt"
        assert restored_file.exists()
        assert "Secret123" in restored_file.read_text(encoding="utf-8")

    def test_restore_not_visible_in_list_files(self):
        """list_files must NOT expose restored files."""
        _, tokenised = self._upload_and_get_tokenised("key: Secret123")
        client.post("/restore", json={"name": "secret_out.txt", "content": tokenised})
        names = [f["name"] for f in client.get("/files").json()]
        assert not any("restored_" in n for n in names)

    def test_restore_without_prior_upload_returns_422(self):
        r = client.post("/restore", json={"name": "out.txt", "content": "[[KW_AAAABBBB]]"})
        assert r.status_code == 422

    def test_restore_roundtrip_content_correct(self, monkeypatch):
        """File written to RESTORED must contain the original values."""
        import server as srv
        original = "user: alice@corp.com  key: Secret123  org: acme-internal"
        _, tokenised = self._upload_and_get_tokenised(original)
        client.post("/restore", json={"name": "check.txt", "content": tokenised})
        assert (srv.RESTORED / "restored_check.txt").read_text() == original


# ── Global mapping accumulation ───────────────────────────────────────────────

class TestGlobalMapping:
    """Mapping from multiple uploads should all be restorable."""

    def test_two_files_share_mapping(self, monkeypatch):
        import server as srv
        fid_a = client.post("/files/text", json={
            "name": "a.txt", "content": "from: alice@corp.com"
        }).json()["file_id"]
        fid_b = client.post("/files/text", json={
            "name": "b.txt", "content": "pass: Secret123"
        }).json()["file_id"]

        tok_a = client.get(f"/files/{fid_a}").text
        tok_b = client.get(f"/files/{fid_b}").text

        combined = tok_a + "\n" + tok_b
        client.post("/restore", json={"name": "combined.txt", "content": combined})

        restored = (srv.RESTORED / "restored_combined.txt").read_text(encoding="utf-8")
        assert "alice@corp.com" in restored
        assert "Secret123" in restored
        assert "[[KW_" not in restored


# ── End-to-end ────────────────────────────────────────────────────────────────

class TestEndToEnd:
    def test_dashboard_html_workflow(self):
        """Upload HTML with PII → get tokenised → simulate AI → restore."""
        html = (
            '<span id="user">alice@corp.com</span>\n'
            'const PASS = "Secret123";\n'
            'fetch("https://api.acme-internal/v2");\n'
        )

        # Step 1: upload (auto replace)
        fid = client.post("/files/text", json={"name": "dashboard.html",
                                                "content": html}).json()["file_id"]

        # Step 2: get tokenised content
        tokenised = client.get(f"/files/{fid}").text
        assert "alice@corp.com" not in tokenised
        assert "[[KW_" in tokenised

        # Step 3: simulate AI generating a Playwright test using tokenised content
        first_token = tokenised.split("[[KW_")[1].split("]]")[0]
        ai_output = (
            f"await page.goto('https://api.[[KW_{first_token}]]/dashboard');\n"
            + tokenised
        )

        # Step 4: restore
        import server as srv
        r = client.post("/restore", json={"name": "test.ts", "content": ai_output})
        assert r.json()["success"] is True

        final = (srv.RESTORED / "restored_test.ts").read_text(encoding="utf-8")
        assert "alice@corp.com" in final
        assert "acme-internal" in final
        assert "[[KW_" not in final
