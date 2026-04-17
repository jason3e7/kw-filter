"""Shared fixtures and helpers for all test modules."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

# Make kw_tools importable from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Namespace builders ─────────────────────────────────────────────────────────

def ns_search(keywords, target, recursive=False, binary=False, output=None):
    return argparse.Namespace(
        keywords=str(keywords),
        target=str(target),
        recursive=recursive,
        binary=binary,
        output=output,
    )


def ns_clear(keywords, target, recursive=False, backup=False, replacement=""):
    return argparse.Namespace(
        keywords=str(keywords),
        target=str(target),
        recursive=recursive,
        backup=backup,
        replacement=replacement,
    )


def ns_replace(keywords, target, mapping, recursive=False, backup=False):
    return argparse.Namespace(
        keywords=str(keywords),
        target=str(target),
        mapping=str(mapping),
        recursive=recursive,
        backup=backup,
    )


def ns_restore(mapping, target, recursive=False, backup=False):
    return argparse.Namespace(
        mapping=str(mapping),
        target=str(target),
        recursive=recursive,
        backup=backup,
    )


# ── Common fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def kw_file(tmp_path):
    """Write a keywords.txt and return its path."""
    def _make(keywords: list):
        p = tmp_path / "keywords.txt"
        p.write_text("\n".join(keywords), encoding="utf-8")
        return p
    return _make


@pytest.fixture
def data_dir(tmp_path):
    """Return a writable temp directory for test data files."""
    d = tmp_path / "data"
    d.mkdir()
    return d
