"""Tests for --dry-run (all commands) and always-on case-insensitive matching."""
from __future__ import annotations

from pathlib import Path

import pytest
from kw_tools import cmd_search, cmd_clear, cmd_replace, cmd_restore, cmd_cleanlog, cmd_remap

from conftest import ns_search, ns_clear, ns_replace, ns_restore, ns_cleanlog, ns_remap


# ── Helpers ───────────────────────────────────────────────────────────────────

def kw(tmp_path, words):
    p = tmp_path / "kw.txt"
    p.write_text("\n".join(words), encoding="utf-8")
    return p


# ══════════════════════════════════════════════════════════════════════════════
# DRY-RUN
# ══════════════════════════════════════════════════════════════════════════════

class TestDryRunClear:
    def test_dry_run_does_not_modify_file(self, tmp_path):
        f = tmp_path / "t.txt"
        original = "secret data here\n"
        f.write_text(original, encoding="utf-8")
        cmd_clear(ns_clear(kw(tmp_path, ["secret"]), f, dry_run=True))
        assert f.read_text(encoding="utf-8") == original

    def test_dry_run_no_backup(self, tmp_path):
        f = tmp_path / "t.txt"
        f.write_text("secret\n", encoding="utf-8")
        cmd_clear(ns_clear(kw(tmp_path, ["secret"]), f, dry_run=True, backup=True))
        assert not (tmp_path / "t.txt.bak").exists()

    def test_dry_run_shows_before_after(self, tmp_path, capsys):
        f = tmp_path / "t.txt"
        f.write_text("remove secret here\n", encoding="utf-8")
        cmd_clear(ns_clear(kw(tmp_path, ["secret"]), f, dry_run=True))
        out = capsys.readouterr().out
        assert "secret" in out
        assert "remove" in out


class TestDryRunReplace:
    def test_dry_run_does_not_modify_file(self, tmp_path):
        f = tmp_path / "t.txt"
        original = "John Doe was here\n"
        f.write_text(original, encoding="utf-8")
        m = tmp_path / "mapping.json"
        cmd_replace(ns_replace(kw(tmp_path, ["John Doe"]), f, m, dry_run=True))
        assert f.read_text(encoding="utf-8") == original

    def test_dry_run_no_mapping_written(self, tmp_path):
        f = tmp_path / "t.txt"
        f.write_text("John Doe\n", encoding="utf-8")
        m = tmp_path / "mapping.json"
        cmd_replace(ns_replace(kw(tmp_path, ["John Doe"]), f, m, dry_run=True))
        assert not m.exists()

    def test_dry_run_shows_before_after(self, tmp_path, capsys):
        f = tmp_path / "t.txt"
        f.write_text("contact John Doe now\n", encoding="utf-8")
        m = tmp_path / "mapping.json"
        cmd_replace(ns_replace(kw(tmp_path, ["John Doe"]), f, m, dry_run=True))
        out = capsys.readouterr().out
        assert "John Doe" in out
        assert "KW_" in out


class TestDryRunRestore:
    def test_dry_run_does_not_modify_file(self, tmp_path):
        import json
        token = "[[KW_ABCD1234]]"
        m = tmp_path / "mapping.json"
        m.write_text(json.dumps({token: "John Doe"}), encoding="utf-8")
        f = tmp_path / "t.txt"
        original = f"contact {token} now\n"
        f.write_text(original, encoding="utf-8")
        cmd_restore(ns_restore(m, f, dry_run=True))
        assert f.read_text(encoding="utf-8") == original

    def test_dry_run_shows_before_after(self, tmp_path, capsys):
        import json
        token = "[[KW_ABCD1234]]"
        m = tmp_path / "mapping.json"
        m.write_text(json.dumps({token: "John Doe"}), encoding="utf-8")
        f = tmp_path / "t.txt"
        f.write_text(f"contact {token} now\n", encoding="utf-8")
        cmd_restore(ns_restore(m, f, dry_run=True))
        out = capsys.readouterr().out
        assert token in out
        assert "John Doe" in out


# ══════════════════════════════════════════════════════════════════════════════
# CASE-INSENSITIVE (always on)
# ══════════════════════════════════════════════════════════════════════════════

class TestCaseInsensitiveSearch:
    def test_matches_uppercase(self, tmp_path, capsys):
        f = tmp_path / "t.txt"
        f.write_text("HELLO world\n", encoding="utf-8")
        cmd_search(ns_search(kw(tmp_path, ["hello"]), f))
        assert "HELLO" in capsys.readouterr().out

    def test_mixed_case_match(self, tmp_path, capsys):
        f = tmp_path / "t.txt"
        f.write_text("Hello World\nhELLO again\n", encoding="utf-8")
        cmd_search(ns_search(kw(tmp_path, ["hello"]), f))
        out = capsys.readouterr().out
        assert "2 occurrence" in out


class TestCaseInsensitiveClear:
    def test_clears_uppercase_keyword(self, tmp_path):
        f = tmp_path / "t.txt"
        f.write_text("ADMIN logged in\n", encoding="utf-8")
        cmd_clear(ns_clear(kw(tmp_path, ["admin"]), f))
        assert "ADMIN" not in f.read_text(encoding="utf-8")

    def test_replacement_applied_to_any_case(self, tmp_path):
        f = tmp_path / "t.txt"
        f.write_text("Admin user ADMIN\n", encoding="utf-8")
        cmd_clear(ns_clear(kw(tmp_path, ["admin"]), f, replacement="[X]"))
        text = f.read_text(encoding="utf-8")
        assert text.count("[X]") == 2
        assert "Admin" not in text
        assert "ADMIN" not in text


class TestCaseInsensitiveReplace:
    def test_same_token_for_different_cases(self, tmp_path):
        import json
        f = tmp_path / "t.txt"
        f.write_text("John john JOHN\n", encoding="utf-8")
        m = tmp_path / "mapping.json"
        cmd_replace(ns_replace(kw(tmp_path, ["John"]), f, m))
        mapping = json.loads(m.read_text(encoding="utf-8"))
        assert len(mapping) == 1
        assert list(mapping.values())[0] == "John"

    def test_restore_brings_back_canonical(self, tmp_path):
        f = tmp_path / "t.txt"
        f.write_text("ALICE logged in\n", encoding="utf-8")
        m = tmp_path / "mapping.json"
        cmd_replace(ns_replace(kw(tmp_path, ["alice"]), f, m))
        cmd_restore(ns_restore(m, f))
        assert "alice" in f.read_text(encoding="utf-8")


class TestCaseInsensitiveCleanlog:
    def test_drops_line_with_uppercase_keyword(self, tmp_path):
        f = tmp_path / "t.txt"
        f.write_text("safe line\nSECRET data here\nanother safe\n", encoding="utf-8")
        cmd_cleanlog(ns_cleanlog(kw(tmp_path, ["secret"]), f))
        text = f.read_text(encoding="utf-8")
        assert "SECRET" not in text
        assert "safe line" in text
        assert "another safe" in text


class TestCaseInsensitiveRemap:
    def test_remaps_uppercase_key(self, tmp_path):
        rf = tmp_path / "remap.txt"
        rf.write_text("alice -> user_a\n", encoding="utf-8")
        f = tmp_path / "t.txt"
        f.write_bytes(b"login: ALICE\n")
        cmd_remap(ns_remap(rf, f))
        data = f.read_bytes()
        assert b"user_a" in data
        assert b"ALICE" not in data


# ══════════════════════════════════════════════════════════════════════════════
# REPLACE -m defaults to mapping.json
# ══════════════════════════════════════════════════════════════════════════════

class TestReplaceDefaultMapping:
    def test_mapping_written(self, tmp_path):
        import json
        f = tmp_path / "t.txt"
        f.write_text("John Doe\n", encoding="utf-8")
        m = tmp_path / "mapping.json"
        cmd_replace(ns_replace(kw(tmp_path, ["John Doe"]), f, m))
        assert m.exists()
        assert "John Doe" in json.loads(m.read_text(encoding="utf-8")).values()

    def test_restore_roundtrip(self, tmp_path):
        f = tmp_path / "t.txt"
        f.write_text("John Doe was here\n", encoding="utf-8")
        m = tmp_path / "mapping.json"
        cmd_replace(ns_replace(kw(tmp_path, ["John Doe"]), f, m))
        cmd_restore(ns_restore(m, f))
        assert "John Doe" in f.read_text(encoding="utf-8")
