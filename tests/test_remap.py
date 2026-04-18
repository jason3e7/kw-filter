"""Tests for the `remap` subcommand (cmd_remap)."""
from __future__ import annotations

from pathlib import Path

import pytest
from kw_tools import cmd_remap, load_remap

from conftest import ns_remap


# ── load_remap ────────────────────────────────────────────────────────────────

class TestLoadRemap:
    def test_basic_pair(self, tmp_path):
        f = tmp_path / "remap.txt"
        f.write_text("192.168.1.1 -> 127.0.0.1\n", encoding="utf-8")
        assert load_remap(str(f)) == {"192.168.1.1": "127.0.0.1"}

    def test_multiple_pairs(self, tmp_path):
        f = tmp_path / "remap.txt"
        f.write_text(
            "alice@corp.com -> user@example.com\n"
            "prod-server -> test-server\n",
            encoding="utf-8",
        )
        result = load_remap(str(f))
        assert result["alice@corp.com"] == "user@example.com"
        assert result["prod-server"] == "test-server"

    def test_comments_and_blank_lines_ignored(self, tmp_path):
        f = tmp_path / "remap.txt"
        f.write_text(
            "# comment\n\n"
            "real-host -> fake-host\n"
            "# another comment\n",
            encoding="utf-8",
        )
        assert load_remap(str(f)) == {"real-host": "fake-host"}

    def test_invalid_line_skipped(self, tmp_path, capsys):
        f = tmp_path / "remap.txt"
        f.write_text("no_arrow_here\nok -> fine\n", encoding="utf-8")
        result = load_remap(str(f))
        assert result == {"ok": "fine"}
        assert "invalid" in capsys.readouterr().err

    def test_replacement_may_contain_arrow(self, tmp_path):
        f = tmp_path / "remap.txt"
        f.write_text("A -> B -> C\n", encoding="utf-8")
        # only first " -> " splits; replacement is "B -> C"
        assert load_remap(str(f)) == {"A": "B -> C"}

    def test_empty_file_warns(self, tmp_path, capsys):
        f = tmp_path / "remap.txt"
        f.write_text("# only comments\n", encoding="utf-8")
        load_remap(str(f))
        assert "empty" in capsys.readouterr().err


# ── Basic replacement ─────────────────────────────────────────────────────────

class TestRemapBasic:
    def _remap_file(self, tmp_path, pairs: dict) -> Path:
        f = tmp_path / "remap.txt"
        f.write_text(
            "\n".join(f"{k} -> {v}" for k, v in pairs.items()),
            encoding="utf-8",
        )
        return f

    def test_single_value_replaced(self, tmp_path):
        rf = self._remap_file(tmp_path, {"192.168.1.100": "127.0.0.1"})
        f = tmp_path / "log.txt"
        f.write_text("connection from 192.168.1.100 refused\n", encoding="utf-8")
        cmd_remap(ns_remap(rf, f))
        assert "127.0.0.1" in f.read_text(encoding="utf-8")
        assert "192.168.1.100" not in f.read_text(encoding="utf-8")

    def test_multiple_values_replaced(self, tmp_path):
        rf = self._remap_file(tmp_path, {
            "alice@corp.com": "user@example.com",
            "prod-db": "test-db",
        })
        f = tmp_path / "log.txt"
        f.write_text(
            "login alice@corp.com on prod-db\n",
            encoding="utf-8",
        )
        cmd_remap(ns_remap(rf, f))
        text = f.read_text(encoding="utf-8")
        assert "user@example.com" in text
        assert "test-db" in text
        assert "alice@corp.com" not in text
        assert "prod-db" not in text

    def test_no_match_file_unchanged(self, tmp_path):
        rf = self._remap_file(tmp_path, {"NOTHERE": "x"})
        f = tmp_path / "log.txt"
        original = "safe content\n"
        f.write_text(original, encoding="utf-8")
        cmd_remap(ns_remap(rf, f))
        assert f.read_text(encoding="utf-8") == original

    def test_no_match_prints_not_found(self, tmp_path, capsys):
        rf = self._remap_file(tmp_path, {"NOTHERE": "x"})
        data = tmp_path / "data"; data.mkdir()
        (data / "log.txt").write_text("safe\n", encoding="utf-8")
        cmd_remap(ns_remap(rf, data))
        assert "No matching" in capsys.readouterr().out

    def test_multiple_occurrences_in_file(self, tmp_path):
        rf = self._remap_file(tmp_path, {"10.0.0.1": "127.0.0.1"})
        f = tmp_path / "log.txt"
        f.write_text("10.0.0.1 connected\n10.0.0.1 disconnected\n", encoding="utf-8")
        cmd_remap(ns_remap(rf, f))
        text = f.read_text(encoding="utf-8")
        assert text.count("127.0.0.1") == 2
        assert "10.0.0.1" not in text


# ── Longest-first matching ────────────────────────────────────────────────────

class TestRemapLongestFirst:
    def test_longer_key_wins(self, tmp_path):
        rf = tmp_path / "remap.txt"
        rf.write_text(
            "192.168.1.1 -> 10.0.0.1\n"
            "192.168.1.100 -> 127.0.0.1\n",
            encoding="utf-8",
        )
        f = tmp_path / "log.txt"
        f.write_text("host 192.168.1.100 connected\n", encoding="utf-8")
        cmd_remap(ns_remap(rf, f))
        text = f.read_text(encoding="utf-8")
        # Should match the longer key 192.168.1.100 → 127.0.0.1
        assert "127.0.0.1" in text
        assert "10.0.0.1" not in text


# ── Dry-run ───────────────────────────────────────────────────────────────────

class TestRemapDryRun:
    def test_dry_run_does_not_modify_file(self, tmp_path):
        rf = tmp_path / "remap.txt"
        rf.write_text("real-ip -> 127.0.0.1\n", encoding="utf-8")
        f = tmp_path / "log.txt"
        original = "connect from real-ip\n"
        f.write_text(original, encoding="utf-8")
        cmd_remap(ns_remap(rf, f, dry_run=True))
        assert f.read_text(encoding="utf-8") == original

    def test_dry_run_shows_before_after(self, tmp_path, capsys):
        rf = tmp_path / "remap.txt"
        rf.write_text("real-ip -> 127.0.0.1\n", encoding="utf-8")
        (tmp_path / "log.txt").write_text("connect from real-ip\n", encoding="utf-8")
        cmd_remap(ns_remap(rf, tmp_path, dry_run=True))
        out = capsys.readouterr().out
        assert "real-ip" in out
        assert "127.0.0.1" in out


# ── Backup ────────────────────────────────────────────────────────────────────

class TestRemapBackup:
    def test_backup_created(self, tmp_path):
        rf = tmp_path / "remap.txt"
        rf.write_text("foo -> bar\n", encoding="utf-8")
        f = tmp_path / "log.txt"
        f.write_text("foo\n", encoding="utf-8")
        cmd_remap(ns_remap(rf, f, backup=True))
        assert (tmp_path / "log.txt.bak").exists()

    def test_backup_contains_original(self, tmp_path):
        rf = tmp_path / "remap.txt"
        rf.write_text("foo -> bar\n", encoding="utf-8")
        f = tmp_path / "log.txt"
        original = "foo bar foo\n"
        f.write_text(original, encoding="utf-8")
        cmd_remap(ns_remap(rf, f, backup=True))
        assert (tmp_path / "log.txt.bak").read_text(encoding="utf-8") == original

    def test_no_backup_by_default(self, tmp_path):
        rf = tmp_path / "remap.txt"
        rf.write_text("foo -> bar\n", encoding="utf-8")
        (tmp_path / "log.txt").write_text("foo\n", encoding="utf-8")
        cmd_remap(ns_remap(rf, tmp_path))
        assert not (tmp_path / "log.txt.bak").exists()


# ── Recursive / multi-file ────────────────────────────────────────────────────

class TestRemapMultiFile:
    def test_remaps_multiple_files(self, tmp_path):
        rf = tmp_path / "remap.txt"
        rf.write_text("SECRET -> REDACTED\n", encoding="utf-8")
        (tmp_path / "a.log").write_text("SECRET found\n", encoding="utf-8")
        (tmp_path / "b.log").write_text("no match\nSECRET here\n", encoding="utf-8")
        cmd_remap(ns_remap(rf, tmp_path))
        assert "REDACTED" in (tmp_path / "a.log").read_text()
        assert "REDACTED" in (tmp_path / "b.log").read_text()

    def test_recursive(self, tmp_path):
        rf = tmp_path / "remap.txt"
        rf.write_text("OLD -> NEW\n", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.log").write_text("value: OLD\n", encoding="utf-8")
        cmd_remap(ns_remap(rf, tmp_path))
        assert "NEW" in (sub / "deep.log").read_text()


# ── Unicode ───────────────────────────────────────────────────────────────────

class TestRemapUnicode:
    def test_unicode_key_and_value(self, tmp_path):
        rf = tmp_path / "remap.txt"
        rf.write_text("張三 -> 使用者A\n", encoding="utf-8")
        f = tmp_path / "log.txt"
        f.write_text("操作者：張三 完成任務\n", encoding="utf-8")
        cmd_remap(ns_remap(rf, f))
        text = f.read_text(encoding="utf-8")
        assert "使用者A" in text
        assert "張三" not in text
