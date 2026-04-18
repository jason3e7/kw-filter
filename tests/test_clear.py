"""Tests for the `clear` subcommand (cmd_clear)."""
from __future__ import annotations

from pathlib import Path

import pytest
from kw_tools import cmd_clear

from conftest import ns_clear


class TestClearBasic:
    def test_keyword_removed(self, kw_file, data_dir):
        kf = kw_file(["Alice"])
        f = data_dir / "f.txt"
        f.write_text("Hello Alice!\n", encoding="utf-8")

        cmd_clear(ns_clear(kf, data_dir))

        assert "Alice" not in f.read_text(encoding="utf-8")

    def test_default_replacement_is_empty(self, kw_file, data_dir):
        kf = kw_file(["SECRET"])
        f = data_dir / "f.txt"
        f.write_text("token: SECRET end\n", encoding="utf-8")

        cmd_clear(ns_clear(kf, data_dir))

        assert f.read_text(encoding="utf-8") == "token:  end\n"

    def test_custom_replacement_string(self, kw_file, data_dir):
        kf = kw_file(["Alice"])
        f = data_dir / "f.txt"
        f.write_text("Author: Alice\n", encoding="utf-8")

        cmd_clear(ns_clear(kf, data_dir, replacement="[REDACTED]"))

        assert f.read_text(encoding="utf-8") == "Author: [REDACTED]\n"

    def test_multiple_occurrences_all_cleared(self, kw_file, data_dir):
        kf = kw_file(["Alice"])
        f = data_dir / "f.txt"
        f.write_text("Alice met Alice and Alice left.\n", encoding="utf-8")

        cmd_clear(ns_clear(kf, data_dir))

        text = f.read_text(encoding="utf-8")
        assert "Alice" not in text

    def test_multiple_keywords_all_cleared(self, kw_file, data_dir):
        kf = kw_file(["Alice", "Bob"])
        f = data_dir / "f.txt"
        f.write_text("Alice and Bob are friends.\n", encoding="utf-8")

        cmd_clear(ns_clear(kf, data_dir))

        text = f.read_text(encoding="utf-8")
        assert "Alice" not in text
        assert "Bob" not in text


class TestClearNoMatch:
    def test_file_unchanged_when_no_keywords(self, kw_file, data_dir):
        kf = kw_file(["ZZZNOTHERE"])
        f = data_dir / "f.txt"
        original = "completely unrelated text\n"
        f.write_text(original, encoding="utf-8")

        cmd_clear(ns_clear(kf, data_dir))

        assert f.read_text(encoding="utf-8") == original

    def test_unrelated_files_untouched(self, kw_file, tmp_path):
        kf = kw_file(["Alice"])
        (tmp_path / "has_kw.txt").write_text("Alice here\n", encoding="utf-8")
        clean = tmp_path / "clean.txt"
        clean.write_text("nothing here\n", encoding="utf-8")

        cmd_clear(ns_clear(kf, tmp_path))

        assert clean.read_text(encoding="utf-8") == "nothing here\n"


class TestClearBackup:
    def test_backup_file_created(self, kw_file, data_dir):
        kf = kw_file(["Alice"])
        f = data_dir / "f.txt"
        f.write_text("Alice\n", encoding="utf-8")

        cmd_clear(ns_clear(kf, data_dir, backup=True))

        assert (data_dir / "f.txt.bak").exists()

    def test_backup_contains_original(self, kw_file, data_dir):
        kf = kw_file(["Alice"])
        f = data_dir / "f.txt"
        original = "Author: Alice\n"
        f.write_text(original, encoding="utf-8")

        cmd_clear(ns_clear(kf, data_dir, backup=True))

        bak = (data_dir / "f.txt.bak").read_text(encoding="utf-8")
        assert bak == original

    def test_no_backup_by_default(self, kw_file, data_dir):
        kf = kw_file(["Alice"])
        (data_dir / "f.txt").write_text("Alice\n", encoding="utf-8")

        cmd_clear(ns_clear(kf, data_dir, backup=False))

        assert not (data_dir / "f.txt.bak").exists()


class TestClearMultipleFiles:
    def test_clears_across_multiple_files(self, kw_file, tmp_path):
        kf = kw_file(["secret"])
        (tmp_path / "a.txt").write_text("secret a\n", encoding="utf-8")
        (tmp_path / "b.txt").write_text("secret b\n", encoding="utf-8")

        cmd_clear(ns_clear(kf, tmp_path))

        assert "secret" not in (tmp_path / "a.txt").read_text(encoding="utf-8")
        assert "secret" not in (tmp_path / "b.txt").read_text(encoding="utf-8")

    def test_recursive_clears_nested_files(self, kw_file, tmp_path):
        kf = kw_file(["secret"])
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.txt").write_text("secret here\n", encoding="utf-8")

        cmd_clear(ns_clear(kf, tmp_path))

        assert "secret" not in (sub / "deep.txt").read_text(encoding="utf-8")


class TestClearUnicode:
    def test_unicode_keyword_cleared(self, kw_file, data_dir):
        kf = kw_file(["張三"])
        f = data_dir / "f.txt"
        f.write_text("作者：張三\n", encoding="utf-8")

        cmd_clear(ns_clear(kf, data_dir))

        assert "張三" not in f.read_text(encoding="utf-8")

    def test_unicode_content_not_corrupted(self, kw_file, data_dir):
        kf = kw_file(["Alice"])
        f = data_dir / "f.txt"
        f.write_text("こんにちは Alice さん\n", encoding="utf-8")

        cmd_clear(ns_clear(kf, data_dir))

        text = f.read_text(encoding="utf-8")
        assert "こんにちは" in text
        assert "さん" in text
        assert "Alice" not in text
