"""Tests for the `cleanlog` subcommand (cmd_cleanlog)."""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from kw_tools import cmd_cleanlog

from conftest import ns_cleanlog


class TestCleanlogBasic:
    def test_line_with_keyword_removed(self, kw_file, data_dir):
        kf = kw_file(["ERROR"])
        f = data_dir / "app.log"
        f.write_text(
            "INFO  all good\n"
            "ERROR something failed\n"
            "INFO  recovered\n",
            encoding="utf-8",
        )

        cmd_cleanlog(ns_cleanlog(kf, data_dir))

        lines = f.read_text(encoding="utf-8").splitlines()
        assert lines == ["INFO  all good", "INFO  recovered"]

    def test_line_without_keyword_kept(self, kw_file, data_dir):
        kf = kw_file(["secret"])
        f = data_dir / "app.log"
        f.write_text("safe line\nanother safe line\n", encoding="utf-8")

        cmd_cleanlog(ns_cleanlog(kf, data_dir))

        assert f.read_text(encoding="utf-8") == "safe line\nanother safe line\n"

    def test_multiple_keywords_any_triggers_removal(self, kw_file, data_dir):
        kf = kw_file(["ERROR", "secret"])
        f = data_dir / "app.log"
        f.write_text(
            "INFO  normal\n"
            "ERROR bad thing\n"
            "DEBUG secret=abc\n"
            "INFO  fine\n",
            encoding="utf-8",
        )

        cmd_cleanlog(ns_cleanlog(kf, data_dir))

        lines = f.read_text(encoding="utf-8").splitlines()
        assert lines == ["INFO  normal", "INFO  fine"]

    def test_keyword_anywhere_in_line_triggers(self, kw_file, data_dir):
        kf = kw_file(["token"])
        f = data_dir / "app.log"
        f.write_text(
            "auth=ok token=abc123 user=bob\n"
            "clean line here\n",
            encoding="utf-8",
        )

        cmd_cleanlog(ns_cleanlog(kf, data_dir))

        lines = f.read_text(encoding="utf-8").splitlines()
        assert lines == ["clean line here"]


class TestCleanlogNoMatch:
    def test_no_match_file_unchanged(self, kw_file, data_dir):
        kf = kw_file(["ZZZNOTHERE"])
        f = data_dir / "app.log"
        original = "line one\nline two\n"
        f.write_text(original, encoding="utf-8")

        cmd_cleanlog(ns_cleanlog(kf, data_dir))

        assert f.read_text(encoding="utf-8") == original

    def test_no_match_prints_not_found(self, kw_file, data_dir, capsys):
        kf = kw_file(["ZZZNOTHERE"])
        (data_dir / "app.log").write_text("safe\n", encoding="utf-8")

        cmd_cleanlog(ns_cleanlog(kf, data_dir))

        assert "No matching lines found" in capsys.readouterr().out


class TestCleanlogAllLinesRemoved:
    def test_all_lines_removed_leaves_empty_file(self, kw_file, data_dir):
        kf = kw_file(["ERROR"])
        f = data_dir / "app.log"
        f.write_text("ERROR line one\nERROR line two\n", encoding="utf-8")

        cmd_cleanlog(ns_cleanlog(kf, data_dir))

        assert f.read_text(encoding="utf-8") == ""


class TestCleanlogDryRun:
    def test_dry_run_does_not_modify_file(self, kw_file, data_dir):
        kf = kw_file(["ERROR"])
        f = data_dir / "app.log"
        original = "INFO  ok\nERROR bad\n"
        f.write_text(original, encoding="utf-8")

        cmd_cleanlog(ns_cleanlog(kf, data_dir, dry_run=True))

        assert f.read_text(encoding="utf-8") == original

    def test_dry_run_shows_lines_to_remove(self, kw_file, data_dir, capsys):
        kf = kw_file(["ERROR"])
        (data_dir / "app.log").write_text("INFO  ok\nERROR bad\n", encoding="utf-8")

        cmd_cleanlog(ns_cleanlog(kf, data_dir, dry_run=True))

        out = capsys.readouterr().out
        assert "ERROR bad" in out
        assert "would be removed" in out

    def test_dry_run_does_not_show_safe_lines(self, kw_file, data_dir, capsys):
        kf = kw_file(["ERROR"])
        (data_dir / "app.log").write_text("INFO  ok\nERROR bad\n", encoding="utf-8")

        cmd_cleanlog(ns_cleanlog(kf, data_dir, dry_run=True))

        out = capsys.readouterr().out
        assert "INFO  ok" not in out


class TestCleanlogStats:
    def test_stats_shows_counts(self, kw_file, data_dir, capsys):
        kf = kw_file(["ERROR"])
        (data_dir / "app.log").write_text(
            "INFO  a\nERROR b\nINFO  c\nERROR d\n", encoding="utf-8"
        )

        cmd_cleanlog(ns_cleanlog(kf, data_dir, stats=True))

        out = capsys.readouterr().out
        assert "2" in out   # removed count
        assert "2" in out   # kept count

    def test_stats_shows_percentage(self, kw_file, data_dir, capsys):
        kf = kw_file(["ERROR"])
        (data_dir / "app.log").write_text(
            "INFO  a\nINFO  b\nINFO  c\nERROR d\n", encoding="utf-8"
        )

        cmd_cleanlog(ns_cleanlog(kf, data_dir, stats=True))

        out = capsys.readouterr().out
        assert "25.0%" in out


class TestCleanlogBackup:
    def test_backup_created(self, kw_file, data_dir):
        kf = kw_file(["ERROR"])
        f = data_dir / "app.log"
        f.write_text("INFO  ok\nERROR bad\n", encoding="utf-8")

        cmd_cleanlog(ns_cleanlog(kf, data_dir, backup=True))

        assert (data_dir / "app.log.bak").exists()

    def test_backup_contains_original(self, kw_file, data_dir):
        kf = kw_file(["ERROR"])
        f = data_dir / "app.log"
        original = "INFO  ok\nERROR bad\n"
        f.write_text(original, encoding="utf-8")

        cmd_cleanlog(ns_cleanlog(kf, data_dir, backup=True))

        assert (data_dir / "app.log.bak").read_text(encoding="utf-8") == original

    def test_no_backup_by_default(self, kw_file, data_dir):
        kf = kw_file(["ERROR"])
        (data_dir / "app.log").write_text("ERROR bad\n", encoding="utf-8")

        cmd_cleanlog(ns_cleanlog(kf, data_dir))

        assert not (data_dir / "app.log.bak").exists()


class TestCleanlogMultipleFiles:
    def test_cleans_multiple_files(self, kw_file, tmp_path):
        kf = kw_file(["SECRET"])
        (tmp_path / "a.log").write_text("ok\nSECRET=xyz\n", encoding="utf-8")
        (tmp_path / "b.log").write_text("ok\nSECRET=abc\n", encoding="utf-8")

        cmd_cleanlog(ns_cleanlog(kf, tmp_path))

        assert (tmp_path / "a.log").read_text(encoding="utf-8") == "ok\n"
        assert (tmp_path / "b.log").read_text(encoding="utf-8") == "ok\n"

    def test_recursive_cleans_nested_logs(self, kw_file, tmp_path):
        kf = kw_file(["ERROR"])
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.log").write_text("INFO  ok\nERROR bad\n", encoding="utf-8")

        cmd_cleanlog(ns_cleanlog(kf, tmp_path))

        lines = (sub / "deep.log").read_text(encoding="utf-8").splitlines()
        assert lines == ["INFO  ok"]


class TestCleanlogSingleFile:
    def test_accepts_single_file_as_target(self, kw_file, tmp_path):
        kf = kw_file(["ERROR"])
        f = tmp_path / "single.log"
        f.write_text("INFO  ok\nERROR bad\n", encoding="utf-8")

        cmd_cleanlog(ns_cleanlog(kf, f))  # pass file directly, not dir

        lines = f.read_text(encoding="utf-8").splitlines()
        assert lines == ["INFO  ok"]


class TestCleanlogUnicode:
    def test_unicode_keyword_in_log(self, kw_file, data_dir):
        kf = kw_file(["機密"])
        f = data_dir / "app.log"
        f.write_text("正常日誌\n包含機密資訊的那行\n另一筆正常\n", encoding="utf-8")

        cmd_cleanlog(ns_cleanlog(kf, data_dir))

        lines = f.read_text(encoding="utf-8").splitlines()
        assert lines == ["正常日誌", "另一筆正常"]

    def test_unicode_content_not_corrupted(self, kw_file, data_dir):
        kf = kw_file(["ERROR"])
        f = data_dir / "app.log"
        f.write_text("INFO 日本語テスト\nERROR 失敗\nINFO 繁體中文\n", encoding="utf-8")

        cmd_cleanlog(ns_cleanlog(kf, data_dir))

        lines = f.read_text(encoding="utf-8").splitlines()
        assert lines == ["INFO 日本語テスト", "INFO 繁體中文"]


class TestCleanlogRealWorldLog:
    """Realistic log format test."""

    def test_apache_access_log_pattern(self, kw_file, data_dir):
        kf = kw_file(["192.168.1.100", "admin@corp.com"])
        f = data_dir / "access.log"
        f.write_text(
            '10.0.0.1 - - [01/Jan/2024:10:00:00] "GET /index.html" 200\n'
            '192.168.1.100 - - [01/Jan/2024:10:00:01] "POST /login" 401\n'
            '10.0.0.2 - admin@corp.com [01/Jan/2024:10:00:02] "GET /admin" 403\n'
            '10.0.0.3 - - [01/Jan/2024:10:00:03] "GET /health" 200\n',
            encoding="utf-8",
        )

        cmd_cleanlog(ns_cleanlog(kf, data_dir))

        lines = f.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert all("GET /index.html" in l or "GET /health" in l for l in lines)

    def test_structured_log_json_lines(self, kw_file, data_dir):
        kf = kw_file(["password", "token"])
        f = data_dir / "app.log"
        f.write_text(
            '{"level":"info","msg":"started"}\n'
            '{"level":"debug","msg":"auth","password":"s3cr3t"}\n'
            '{"level":"info","msg":"request","path":"/api"}\n'
            '{"level":"debug","msg":"cache","token":"abc123"}\n'
            '{"level":"info","msg":"done"}\n',
            encoding="utf-8",
        )

        cmd_cleanlog(ns_cleanlog(kf, data_dir))

        lines = f.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        assert all("password" not in l and "token" not in l for l in lines)
