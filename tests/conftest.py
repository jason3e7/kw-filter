"""Shared fixtures and helpers for all test modules."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

# Make kw_tools importable from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Namespace builders ─────────────────────────────────────────────────────────

def ns_search(keywords, target, recursive=False, binary=False, output=None,
              ignore_case=False):
    return argparse.Namespace(
        keywords=str(keywords),
        target=str(target),
        recursive=recursive,
        binary=binary,
        output=output,
        ignore_case=ignore_case,
    )


def ns_clear(keywords, target, recursive=False, backup=False, replacement="",
             dry_run=False, ignore_case=False):
    return argparse.Namespace(
        keywords=str(keywords),
        target=str(target),
        recursive=recursive,
        backup=backup,
        replacement=replacement,
        dry_run=dry_run,
        ignore_case=ignore_case,
    )


def ns_replace(keywords, target, mapping="mapping.json", recursive=False,
               backup=False, dry_run=False, ignore_case=False):
    return argparse.Namespace(
        keywords=str(keywords),
        target=str(target),
        mapping=str(mapping),
        recursive=recursive,
        backup=backup,
        dry_run=dry_run,
        ignore_case=ignore_case,
    )


def ns_restore(mapping, target, recursive=False, backup=False, dry_run=False):
    return argparse.Namespace(
        mapping=str(mapping),
        target=str(target),
        recursive=recursive,
        backup=backup,
        dry_run=dry_run,
    )


def ns_cleanlog(keywords, target, recursive=False, backup=False,
                dry_run=False, stats=False, ignore_case=False):
    return argparse.Namespace(
        keywords=str(keywords),
        target=str(target),
        recursive=recursive,
        backup=backup,
        dry_run=dry_run,
        stats=stats,
        ignore_case=ignore_case,
    )


def ns_remap(remap, target, recursive=False, backup=False, dry_run=False,
             ignore_case=False):
    return argparse.Namespace(
        remap=str(remap),
        target=str(target),
        recursive=recursive,
        backup=backup,
        dry_run=dry_run,
        ignore_case=ignore_case,
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
