"""Tests for --dry-run and --ignore-case/-i across all commands."""
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
# IGNORE-CASE
# ══════════════════════════════════════════════════════════════════════════════

class TestIgnoreCaseSearch:
    def test_matches_uppercase(self, tmp_path, capsys):
        f = tmp_path / "t.txt"
        f.write_text("HELLO world\n", encoding="utf-8")
        cmd_search(ns_search(kw(tmp_path, ["hello"]), f, ignore_case=True))
        assert "HELLO" in capsys.readouterr().out

    def test_no_match_without_flag(self, tmp_path, capsys):
        f = tmp_path / "t.txt"
        f.write_text("HELLO world\n", encoding="utf-8")
        cmd_search(ns_search(kw(tmp_path, ["hello"]), f, ignore_case=False))
        assert "No keywords found" in capsys.readouterr().out

    def test_mixed_case_match(self, tmp_path, capsys):
        f = tmp_path / "t.txt"
        f.write_text("Hello World\nhELLO again\n", encoding="utf-8")
        cmd_search(ns_search(kw(tmp_path, ["hello"]), f, ignore_case=True))
        out = capsys.readouterr().out
        assert "2 occurrence" in out


class TestIgnoreCaseClear:
    def test_clears_uppercase_keyword(self, tmp_path):
        f = tmp_path / "t.txt"
        f.write_text("ADMIN logged in\n", encoding="utf-8")
        cmd_clear(ns_clear(kw(tmp_path, ["admin"]), f, ignore_case=True))
        text = f.read_text(encoding="utf-8")
        assert "ADMIN" not in text

    def test_case_sensitive_does_not_clear(self, tmp_path):
        f = tmp_path / "t.txt"
        original = "ADMIN logged in\n"
        f.write_text(original, encoding="utf-8")
        cmd_clear(ns_clear(kw(tmp_path, ["admin"]), f, ignore_case=False))
        assert f.read_text(encoding="utf-8") == original

    def test_replacement_applied_to_any_case(self, tmp_path):
        f = tmp_path / "t.txt"
        f.write_text("Admin user ADMIN\n", encoding="utf-8")
        cmd_clear(ns_clear(kw(tmp_path, ["admin"]), f,
                           replacement="[X]", ignore_case=True))
        text = f.read_text(encoding="utf-8")
        assert text.count("[X]") == 2
        assert "Admin" not in text
        assert "ADMIN" not in text


class TestIgnoreCaseReplace:
    def test_same_token_for_different_cases(self, tmp_path):
        import json
        f = tmp_path / "t.txt"
        f.write_text("John john JOHN\n", encoding="utf-8")
        m = tmp_path / "mapping.json"
        cmd_replace(ns_replace(kw(tmp_path, ["John"]), f, m, ignore_case=True))
        mapping = json.loads(m.read_text(encoding="utf-8"))
        # all three variants should map to the same token → 1 entry in mapping
        assert len(mapping) == 1
        assert list(mapping.values())[0] == "John"  # canonical form from keyword file

    def test_token_canonical_keyword_stored(self, tmp_path):
        import json
        f = tmp_path / "t.txt"
        f.write_text("alice ALICE Alice\n", encoding="utf-8")
        m = tmp_path / "mapping.json"
        cmd_replace(ns_replace(kw(tmp_path, ["alice"]), f, m, ignore_case=True))
        mapping = json.loads(m.read_text(encoding="utf-8"))
        assert list(mapping.values())[0] == "alice"

    def test_restore_brings_back_canonical(self, tmp_path):
        import json
        f = tmp_path / "t.txt"
        f.write_text("ALICE logged in\n", encoding="utf-8")
        m = tmp_path / "mapping.json"
        cmd_replace(ns_replace(kw(tmp_path, ["alice"]), f, m, ignore_case=True))
        # now restore
        cmd_restore(ns_restore(m, f))
        text = f.read_text(encoding="utf-8")
        # restored to canonical keyword (lowercase "alice")
        assert "alice" in text


class TestIgnoreCaseCleanlog:
    def test_drops_line_with_uppercase_keyword(self, tmp_path):
        f = tmp_path / "t.txt"
        f.write_text("safe line\nSECRET data here\nanother safe\n", encoding="utf-8")
        cmd_cleanlog(ns_cleanlog(kw(tmp_path, ["secret"]), f, ignore_case=True))
        text = f.read_text(encoding="utf-8")
        assert "SECRET" not in text
        assert "safe line" in text
        assert "another safe" in text

    def test_case_sensitive_keeps_uppercase(self, tmp_path):
        f = tmp_path / "t.txt"
        original = "safe line\nSECRET data here\nanother safe\n"
        f.write_text(original, encoding="utf-8")
        cmd_cleanlog(ns_cleanlog(kw(tmp_path, ["secret"]), f, ignore_case=False))
        assert f.read_text(encoding="utf-8") == original


class TestIgnoreCaseRemap:
    def test_remaps_uppercase_key(self, tmp_path):
        rf = tmp_path / "remap.txt"
        rf.write_text("alice -> user_a\n", encoding="utf-8")
        f = tmp_path / "t.txt"
        f.write_bytes(b"login: ALICE\n")
        cmd_remap(ns_remap(rf, f, ignore_case=True))
        data = f.read_bytes()
        assert b"user_a" in data
        assert b"ALICE" not in data

    def test_case_sensitive_does_not_remap_uppercase(self, tmp_path):
        rf = tmp_path / "remap.txt"
        rf.write_text("alice -> user_a\n", encoding="utf-8")
        f = tmp_path / "t.txt"
        original = b"login: ALICE\n"
        f.write_bytes(original)
        cmd_remap(ns_remap(rf, f, ignore_case=False))
        assert f.read_bytes() == original


# ══════════════════════════════════════════════════════════════════════════════
# REPLACE -m defaults to mapping.json
# ══════════════════════════════════════════════════════════════════════════════

class TestReplaceDefaultMapping:
    def test_mapping_default_is_mapping_json(self, tmp_path):
        import json, os
        f = tmp_path / "t.txt"
        f.write_text("John Doe\n", encoding="utf-8")
        m = tmp_path / "mapping.json"
        cmd_replace(ns_replace(kw(tmp_path, ["John Doe"]), f, m))
        assert m.exists()
        mapping = json.loads(m.read_text(encoding="utf-8"))
        assert "John Doe" in mapping.values()

    def test_restore_default_mapping_json(self, tmp_path):
        import json
        f = tmp_path / "t.txt"
        f.write_text("John Doe was here\n", encoding="utf-8")
        m = tmp_path / "mapping.json"
        cmd_replace(ns_replace(kw(tmp_path, ["John Doe"]), f, m))
        cmd_restore(ns_restore(m, f))
        assert "John Doe" in f.read_text(encoding="utf-8")
