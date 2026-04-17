"""Tests for the `replace` subcommand (cmd_replace)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from kw_tools import cmd_replace

from conftest import ns_replace

TOKEN_RE = re.compile(r"\[\[KW_[0-9A-F]{8}\]\]")


class TestReplaceBasic:
    def test_keyword_replaced_with_token(self, kw_file, data_dir, tmp_path):
        kf = kw_file(["Alice"])
        (data_dir / "f.txt").write_text("Hello Alice!\n", encoding="utf-8")
        mp = tmp_path / "mapping.json"

        cmd_replace(ns_replace(kf, data_dir, mp))

        text = (data_dir / "f.txt").read_text(encoding="utf-8")
        assert "Alice" not in text
        assert TOKEN_RE.search(text)

    def test_mapping_file_created(self, kw_file, data_dir, tmp_path):
        kf = kw_file(["Alice"])
        (data_dir / "f.txt").write_text("Alice\n", encoding="utf-8")
        mp = tmp_path / "mapping.json"

        cmd_replace(ns_replace(kf, data_dir, mp))

        assert mp.exists()

    def test_mapping_maps_token_to_original(self, kw_file, data_dir, tmp_path):
        kf = kw_file(["Alice"])
        (data_dir / "f.txt").write_text("Alice\n", encoding="utf-8")
        mp = tmp_path / "mapping.json"

        cmd_replace(ns_replace(kf, data_dir, mp))

        mapping = json.loads(mp.read_text(encoding="utf-8"))
        assert "Alice" in mapping.values()

    def test_token_format(self, kw_file, data_dir, tmp_path):
        kf = kw_file(["Alice"])
        (data_dir / "f.txt").write_text("Alice\n", encoding="utf-8")
        mp = tmp_path / "mapping.json"

        cmd_replace(ns_replace(kf, data_dir, mp))

        mapping = json.loads(mp.read_text(encoding="utf-8"))
        for token in mapping:
            assert TOKEN_RE.fullmatch(token), f"Bad token format: {token!r}"


class TestReplaceStability:
    def test_same_keyword_gets_same_token_in_one_file(self, kw_file, data_dir, tmp_path):
        kf = kw_file(["Alice"])
        (data_dir / "f.txt").write_text("Alice and Alice again.\n", encoding="utf-8")
        mp = tmp_path / "mapping.json"

        cmd_replace(ns_replace(kf, data_dir, mp))

        text = (data_dir / "f.txt").read_text(encoding="utf-8")
        tokens = TOKEN_RE.findall(text)
        assert len(tokens) == 2
        assert tokens[0] == tokens[1]

    def test_same_keyword_same_token_across_files(self, kw_file, tmp_path):
        kf = kw_file(["Alice"])
        fa = tmp_path / "a.txt"
        fb = tmp_path / "b.txt"
        fa.write_text("Alice\n", encoding="utf-8")
        fb.write_text("Alice\n", encoding="utf-8")
        mp = tmp_path / "mapping.json"

        cmd_replace(ns_replace(kf, tmp_path, mp))

        ta = TOKEN_RE.search(fa.read_text(encoding="utf-8")).group(0)
        tb = TOKEN_RE.search(fb.read_text(encoding="utf-8")).group(0)
        assert ta == tb

    def test_different_keywords_get_different_tokens(self, kw_file, data_dir, tmp_path):
        kf = kw_file(["Alice", "Bob"])
        (data_dir / "f.txt").write_text("Alice and Bob\n", encoding="utf-8")
        mp = tmp_path / "mapping.json"

        cmd_replace(ns_replace(kf, data_dir, mp))

        mapping = json.loads(mp.read_text(encoding="utf-8"))
        tokens = list(mapping.keys())
        assert len(tokens) == 2
        assert tokens[0] != tokens[1]


class TestReplaceNoMatch:
    def test_no_match_mapping_is_empty(self, kw_file, data_dir, tmp_path):
        kf = kw_file(["ZZZNOTHERE"])
        (data_dir / "f.txt").write_text("unrelated text\n", encoding="utf-8")
        mp = tmp_path / "mapping.json"

        cmd_replace(ns_replace(kf, data_dir, mp))

        mapping = json.loads(mp.read_text(encoding="utf-8"))
        assert mapping == {}

    def test_no_match_file_unchanged(self, kw_file, data_dir, tmp_path):
        kf = kw_file(["ZZZNOTHERE"])
        f = data_dir / "f.txt"
        original = "unrelated text\n"
        f.write_text(original, encoding="utf-8")
        mp = tmp_path / "mapping.json"

        cmd_replace(ns_replace(kf, data_dir, mp))

        assert f.read_text(encoding="utf-8") == original


class TestReplaceBackup:
    def test_backup_created(self, kw_file, data_dir, tmp_path):
        kf = kw_file(["Alice"])
        (data_dir / "f.txt").write_text("Alice\n", encoding="utf-8")
        mp = tmp_path / "mapping.json"

        cmd_replace(ns_replace(kf, data_dir, mp, backup=True))

        assert (data_dir / "f.txt.bak").exists()

    def test_backup_contains_original(self, kw_file, data_dir, tmp_path):
        kf = kw_file(["Alice"])
        original = "Author: Alice\n"
        (data_dir / "f.txt").write_text(original, encoding="utf-8")
        mp = tmp_path / "mapping.json"

        cmd_replace(ns_replace(kf, data_dir, mp, backup=True))

        bak = (data_dir / "f.txt.bak").read_text(encoding="utf-8")
        assert bak == original


class TestReplaceUnicode:
    def test_unicode_keyword_replaced(self, kw_file, data_dir, tmp_path):
        kf = kw_file(["張三"])
        (data_dir / "f.txt").write_text("作者：張三\n", encoding="utf-8")
        mp = tmp_path / "mapping.json"

        cmd_replace(ns_replace(kf, data_dir, mp))

        text = (data_dir / "f.txt").read_text(encoding="utf-8")
        assert "張三" not in text
        assert TOKEN_RE.search(text)

    def test_unicode_mapping_value(self, kw_file, data_dir, tmp_path):
        kf = kw_file(["張三"])
        (data_dir / "f.txt").write_text("張三\n", encoding="utf-8")
        mp = tmp_path / "mapping.json"

        cmd_replace(ns_replace(kf, data_dir, mp))

        mapping = json.loads(mp.read_text(encoding="utf-8"))
        assert "張三" in mapping.values()


class TestReplaceLongestWins:
    def test_long_keyword_not_split_by_short(self, kw_file, data_dir, tmp_path):
        kf = kw_file(["John", "John Doe"])
        (data_dir / "f.txt").write_text("John Doe was here\n", encoding="utf-8")
        mp = tmp_path / "mapping.json"

        cmd_replace(ns_replace(kf, data_dir, mp))

        mapping = json.loads(mp.read_text(encoding="utf-8"))
        assert "John Doe" in mapping.values()
        assert "John" not in mapping.values()
