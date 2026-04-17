"""Tests for the `restore` subcommand (cmd_restore)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from kw_tools import cmd_replace, cmd_restore

from conftest import ns_replace, ns_restore


def write_mapping(path: Path, mapping: dict) -> None:
    path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")


class TestRestoreBasic:
    def test_token_replaced_with_original(self, data_dir, tmp_path):
        mapping = {"[[KW_AABBCCDD]]": "Alice"}
        mp = tmp_path / "mapping.json"
        write_mapping(mp, mapping)

        f = data_dir / "f.txt"
        f.write_text("Hello [[KW_AABBCCDD]]!\n", encoding="utf-8")

        cmd_restore(ns_restore(mp, data_dir))

        assert f.read_text(encoding="utf-8") == "Hello Alice!\n"

    def test_multiple_tokens_all_restored(self, data_dir, tmp_path):
        mapping = {
            "[[KW_AABBCCDD]]": "Alice",
            "[[KW_11223344]]": "Bob",
        }
        mp = tmp_path / "mapping.json"
        write_mapping(mp, mapping)

        f = data_dir / "f.txt"
        f.write_text("[[KW_AABBCCDD]] met [[KW_11223344]]\n", encoding="utf-8")

        cmd_restore(ns_restore(mp, data_dir))

        assert f.read_text(encoding="utf-8") == "Alice met Bob\n"

    def test_same_token_multiple_occurrences(self, data_dir, tmp_path):
        mapping = {"[[KW_AABBCCDD]]": "Alice"}
        mp = tmp_path / "mapping.json"
        write_mapping(mp, mapping)

        f = data_dir / "f.txt"
        f.write_text("[[KW_AABBCCDD]] and [[KW_AABBCCDD]] again.\n", encoding="utf-8")

        cmd_restore(ns_restore(mp, data_dir))

        assert f.read_text(encoding="utf-8") == "Alice and Alice again.\n"


class TestRestoreNoOp:
    def test_file_without_tokens_unchanged(self, data_dir, tmp_path):
        mapping = {"[[KW_AABBCCDD]]": "Alice"}
        mp = tmp_path / "mapping.json"
        write_mapping(mp, mapping)

        f = data_dir / "clean.txt"
        original = "no tokens here\n"
        f.write_text(original, encoding="utf-8")

        cmd_restore(ns_restore(mp, data_dir))

        assert f.read_text(encoding="utf-8") == original

    def test_empty_mapping_no_changes(self, data_dir, tmp_path, capsys):
        mp = tmp_path / "mapping.json"
        write_mapping(mp, {})

        (data_dir / "f.txt").write_text("some text\n", encoding="utf-8")
        cmd_restore(ns_restore(mp, data_dir))

        out = capsys.readouterr().out
        assert "empty" in out.lower()


class TestRestoreErrors:
    def test_missing_mapping_file_exits(self, data_dir, tmp_path):
        mp = tmp_path / "nonexistent.json"

        with pytest.raises(SystemExit) as exc_info:
            cmd_restore(ns_restore(mp, data_dir))

        assert exc_info.value.code != 0


class TestRestoreBackup:
    def test_backup_created(self, data_dir, tmp_path):
        mapping = {"[[KW_AABBCCDD]]": "Alice"}
        mp = tmp_path / "mapping.json"
        write_mapping(mp, mapping)

        f = data_dir / "f.txt"
        f.write_text("Hello [[KW_AABBCCDD]]\n", encoding="utf-8")

        cmd_restore(ns_restore(mp, data_dir, backup=True))

        assert (data_dir / "f.txt.bak").exists()

    def test_backup_contains_pre_restore_content(self, data_dir, tmp_path):
        mapping = {"[[KW_AABBCCDD]]": "Alice"}
        mp = tmp_path / "mapping.json"
        write_mapping(mp, mapping)

        f = data_dir / "f.txt"
        tokenised = "Hello [[KW_AABBCCDD]]\n"
        f.write_text(tokenised, encoding="utf-8")

        cmd_restore(ns_restore(mp, data_dir, backup=True))

        bak = (data_dir / "f.txt.bak").read_text(encoding="utf-8")
        assert bak == tokenised


class TestRestoreMultipleFiles:
    def test_restores_across_multiple_files(self, tmp_path):
        mapping = {"[[KW_AABBCCDD]]": "Alice"}
        mp = tmp_path / "mapping.json"
        write_mapping(mp, mapping)

        (tmp_path / "a.txt").write_text("[[KW_AABBCCDD]]\n", encoding="utf-8")
        (tmp_path / "b.txt").write_text("[[KW_AABBCCDD]]\n", encoding="utf-8")

        cmd_restore(ns_restore(mp, tmp_path))

        assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "Alice\n"
        assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "Alice\n"

    def test_recursive_restores_nested(self, tmp_path):
        mapping = {"[[KW_AABBCCDD]]": "Alice"}
        mp = tmp_path / "mapping.json"
        write_mapping(mp, mapping)

        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.txt").write_text("[[KW_AABBCCDD]]\n", encoding="utf-8")

        cmd_restore(ns_restore(mp, tmp_path, recursive=True))

        assert (sub / "deep.txt").read_text(encoding="utf-8") == "Alice\n"


class TestRestoreRoundtrip:
    """Full replace → restore cycle must return exact original content."""

    def test_single_file_roundtrip(self, kw_file, data_dir, tmp_path):
        kf = kw_file(["Alice", "Bob"])
        original = "Alice and Bob are colleagues at Acme.\nAlice leads the project.\n"
        f = data_dir / "f.txt"
        f.write_text(original, encoding="utf-8")
        mp = tmp_path / "mapping.json"

        cmd_replace(ns_replace(kf, data_dir, mp))
        assert f.read_text(encoding="utf-8") != original  # sanity: was changed

        cmd_restore(ns_restore(mp, data_dir))
        assert f.read_text(encoding="utf-8") == original

    def test_multi_file_roundtrip(self, kw_file, tmp_path):
        kf = kw_file(["secret", "user@example.com"])
        originals = {
            "a.txt": "Token: secret, contact: user@example.com\n",
            "b.txt": "secret appears again here\n",
            "c.txt": "no keywords in this file\n",
        }
        for name, text in originals.items():
            (tmp_path / name).write_text(text, encoding="utf-8")
        mp = tmp_path / "mapping.json"

        cmd_replace(ns_replace(kf, tmp_path, mp))
        cmd_restore(ns_restore(mp, tmp_path))

        for name, text in originals.items():
            assert (tmp_path / name).read_text(encoding="utf-8") == text

    def test_unicode_roundtrip(self, kw_file, data_dir, tmp_path):
        kf = kw_file(["張三", "李四"])
        original = "作者：張三，審閱：李四\n張三 完成了報告。\n"
        f = data_dir / "f.txt"
        f.write_text(original, encoding="utf-8")
        mp = tmp_path / "mapping.json"

        cmd_replace(ns_replace(kf, data_dir, mp))
        cmd_restore(ns_restore(mp, data_dir))

        assert f.read_text(encoding="utf-8") == original
