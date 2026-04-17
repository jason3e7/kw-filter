"""Unit tests for utility functions: load_keywords, sorted_keywords,
build_pattern, keyword_exists_bsearch."""
from __future__ import annotations

import pytest
from kw_tools import (
    build_pattern,
    keyword_exists_bsearch,
    load_keywords,
    sorted_keywords,
)


class TestLoadKeywords:
    def test_basic(self, tmp_path):
        f = tmp_path / "kw.txt"
        f.write_text("Alice\nBob\nCarol\n", encoding="utf-8")
        assert load_keywords(str(f)) == ["Alice", "Bob", "Carol"]

    def test_comments_stripped(self, tmp_path):
        f = tmp_path / "kw.txt"
        f.write_text("# this is a comment\nAlice\n# another\nBob\n", encoding="utf-8")
        assert load_keywords(str(f)) == ["Alice", "Bob"]

    def test_blank_lines_ignored(self, tmp_path):
        f = tmp_path / "kw.txt"
        f.write_text("\nAlice\n\n\nBob\n\n", encoding="utf-8")
        assert load_keywords(str(f)) == ["Alice", "Bob"]

    def test_whitespace_trimmed(self, tmp_path):
        f = tmp_path / "kw.txt"
        f.write_text("  Alice  \n  Bob\n", encoding="utf-8")
        assert load_keywords(str(f)) == ["Alice", "Bob"]

    def test_empty_file_returns_empty_list(self, tmp_path):
        f = tmp_path / "kw.txt"
        f.write_text("", encoding="utf-8")
        assert load_keywords(str(f)) == []

    def test_only_comments_returns_empty(self, tmp_path):
        f = tmp_path / "kw.txt"
        f.write_text("# just a comment\n# another\n", encoding="utf-8")
        assert load_keywords(str(f)) == []

    def test_unicode_keywords(self, tmp_path):
        f = tmp_path / "kw.txt"
        f.write_text("張三\n李四\n王五\n", encoding="utf-8")
        assert load_keywords(str(f)) == ["張三", "李四", "王五"]

    def test_multiword_keyword(self, tmp_path):
        f = tmp_path / "kw.txt"
        f.write_text("John Doe\nAcme Corp\n", encoding="utf-8")
        assert load_keywords(str(f)) == ["John Doe", "Acme Corp"]


class TestSortedKeywords:
    def test_longest_first(self):
        kws = ["ab", "abcde", "abc", "a"]
        result = sorted_keywords(kws)
        assert result == ["abcde", "abc", "ab", "a"]

    def test_equal_length_preserved(self):
        kws = ["foo", "bar", "baz"]
        result = sorted_keywords(kws)
        assert len(result) == 3
        assert all(len(w) == 3 for w in result)

    def test_single_keyword(self):
        assert sorted_keywords(["hello"]) == ["hello"]

    def test_empty_list(self):
        assert sorted_keywords([]) == []


class TestBuildPattern:
    def test_matches_keyword(self):
        p = build_pattern(["Alice", "Bob"])
        assert p.search("Hello Alice how are you")
        assert p.search("Hi Bob!")

    def test_no_match(self):
        p = build_pattern(["Alice", "Bob"])
        assert p.search("Hello Carol") is None

    def test_case_sensitive_by_default(self):
        p = build_pattern(["Alice"])
        assert p.search("Alice")
        assert p.search("ALICE") is None  # case-sensitive

    def test_longest_match_wins(self):
        p = build_pattern(["John", "John Doe"])
        m = p.search("John Doe was here")
        assert m.group(0) == "John Doe"

    def test_special_chars_escaped(self):
        p = build_pattern(["user@example.com"])
        assert p.search("contact: user@example.com please")
        assert p.search("userXexample.com") is None


class TestKeywordExistsBsearch:
    def test_found(self):
        kws = sorted(["Alice", "Bob", "Carol"])
        assert keyword_exists_bsearch(kws, "Bob") is True

    def test_not_found(self):
        kws = sorted(["Alice", "Bob", "Carol"])
        assert keyword_exists_bsearch(kws, "Dave") is False

    def test_empty_list(self):
        assert keyword_exists_bsearch([], "anything") is False

    def test_single_element_found(self):
        assert keyword_exists_bsearch(["Alice"], "Alice") is True

    def test_single_element_not_found(self):
        assert keyword_exists_bsearch(["Alice"], "Bob") is False
