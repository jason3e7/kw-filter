"""Tests for the `search` subcommand (cmd_search)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from kw_tools import cmd_search

from conftest import ns_search


class TestSearchBasic:
    def test_finds_single_keyword(self, kw_file, data_dir, capsys):
        kf = kw_file(["Alice"])
        (data_dir / "file.txt").write_text("Hello Alice!\n", encoding="utf-8")

        cmd_search(ns_search(kf, data_dir))

        out = capsys.readouterr().out
        assert "Alice" in out
        assert "line" in out

    def test_reports_correct_line_and_col(self, kw_file, data_dir, capsys):
        kf = kw_file(["target"])
        (data_dir / "f.txt").write_text("line one\nfound target here\nline three\n",
                                        encoding="utf-8")

        cmd_search(ns_search(kf, data_dir))

        out = capsys.readouterr().out
        assert "line     2" in out
        assert "col    7" in out  # :>4 right-pads to width 4 → "   7"

    def test_no_match_prints_not_found(self, kw_file, data_dir, capsys):
        kf = kw_file(["ZZZNOTHERE"])
        (data_dir / "f.txt").write_text("completely unrelated text\n", encoding="utf-8")

        cmd_search(ns_search(kf, data_dir))

        out = capsys.readouterr().out
        assert "No keywords found" in out

    def test_empty_directory_no_crash(self, kw_file, data_dir, capsys):
        kf = kw_file(["Alice"])
        cmd_search(ns_search(kf, data_dir))
        out = capsys.readouterr().out
        assert "No keywords found" in out


class TestSearchMultiple:
    def test_multiple_keywords_same_file(self, kw_file, data_dir, capsys):
        kf = kw_file(["Alice", "Bob"])
        (data_dir / "f.txt").write_text("Alice met Bob today.\n", encoding="utf-8")

        cmd_search(ns_search(kf, data_dir))

        out = capsys.readouterr().out
        assert "Alice" in out
        assert "Bob" in out
        assert "2 occurrence(s)" in out

    def test_same_keyword_multiple_times_on_one_line(self, kw_file, data_dir, capsys):
        kf = kw_file(["Alice"])
        (data_dir / "f.txt").write_text("Alice and Alice went out.\n", encoding="utf-8")

        cmd_search(ns_search(kf, data_dir))

        out = capsys.readouterr().out
        assert "2 occurrence(s)" in out

    def test_multiple_files(self, kw_file, data_dir, capsys):
        kf = kw_file(["secret"])
        (data_dir / "a.txt").write_text("secret here\n", encoding="utf-8")
        (data_dir / "b.txt").write_text("secret there\n", encoding="utf-8")
        (data_dir / "c.txt").write_text("nothing\n", encoding="utf-8")

        cmd_search(ns_search(kf, data_dir))

        out = capsys.readouterr().out
        assert "2 file(s)" in out
        assert "a.txt" in out
        assert "b.txt" in out

    def test_total_count_correct(self, kw_file, data_dir, capsys):
        kf = kw_file(["x"])
        (data_dir / "f.txt").write_text("x x x\nx\n", encoding="utf-8")

        cmd_search(ns_search(kf, data_dir))

        out = capsys.readouterr().out
        assert "4 occurrence(s)" in out


class TestSearchRecursive:
    def test_recursive_finds_nested_files(self, kw_file, data_dir, capsys):
        kf = kw_file(["needle"])
        sub = data_dir / "subdir"
        sub.mkdir()
        (sub / "deep.txt").write_text("needle found here\n", encoding="utf-8")
        (data_dir / "top.txt").write_text("nothing\n", encoding="utf-8")

        cmd_search(ns_search(kf, data_dir, recursive=True))

        out = capsys.readouterr().out
        assert "deep.txt" in out
        assert "1 occurrence(s)" in out

    def test_non_recursive_skips_subdirs(self, kw_file, data_dir, capsys):
        kf = kw_file(["needle"])
        sub = data_dir / "subdir"
        sub.mkdir()
        (sub / "deep.txt").write_text("needle found here\n", encoding="utf-8")

        cmd_search(ns_search(kf, data_dir, recursive=False))

        out = capsys.readouterr().out
        assert "No keywords found" in out


class TestSearchUnicode:
    def test_unicode_keyword(self, kw_file, data_dir, capsys):
        kf = kw_file(["張三"])
        (data_dir / "f.txt").write_text("作者：張三\n", encoding="utf-8")

        cmd_search(ns_search(kf, data_dir))

        out = capsys.readouterr().out
        assert "張三" in out

    def test_unicode_in_file_no_crash(self, kw_file, data_dir, capsys):
        kf = kw_file(["Alice"])
        (data_dir / "f.txt").write_text("こんにちは Alice さん\n", encoding="utf-8")

        cmd_search(ns_search(kf, data_dir))

        out = capsys.readouterr().out
        assert "Alice" in out


class TestSearchJsonOutput:
    def test_json_output_created(self, kw_file, data_dir, tmp_path, capsys):
        kf = kw_file(["Alice"])
        (data_dir / "f.txt").write_text("Alice is here\n", encoding="utf-8")
        out_path = tmp_path / "results.json"

        cmd_search(ns_search(kf, data_dir, output=str(out_path)))

        assert out_path.exists()

    def test_json_output_structure(self, kw_file, data_dir, tmp_path):
        kf = kw_file(["Alice"])
        (data_dir / "f.txt").write_text("Hello Alice\n", encoding="utf-8")
        out_path = tmp_path / "results.json"

        cmd_search(ns_search(kf, data_dir, output=str(out_path)))

        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) == 1
        entry = data[0]
        assert entry["keyword"] == "Alice"
        assert entry["line"] == 1
        assert entry["col"] == 7
        assert "context" in entry
        assert "file" in entry

    def test_json_no_output_when_no_match(self, kw_file, data_dir, tmp_path, capsys):
        kf = kw_file(["ZZZNOTHERE"])
        (data_dir / "f.txt").write_text("unrelated\n", encoding="utf-8")
        out_path = tmp_path / "results.json"

        cmd_search(ns_search(kf, data_dir, output=str(out_path)))

        assert not out_path.exists()


class TestSearchLongestMatchWins:
    def test_longer_keyword_matched_not_shorter(self, kw_file, data_dir, capsys):
        kf = kw_file(["John", "John Doe"])
        (data_dir / "f.txt").write_text("John Doe was here\n", encoding="utf-8")

        cmd_search(ns_search(kf, data_dir))

        out = capsys.readouterr().out
        assert "'John Doe'" in out
        assert "1 occurrence(s)" in out
