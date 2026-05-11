#!/usr/bin/env python3
"""
kw_tools.py — Keyword filter toolkit for AI data preparation.

Subcommands (each independently runnable):
  search   Find all keyword occurrences in files
  clear    Erase keywords in-place
  replace  Replace keywords with tokens + emit mapping table
  restore  Reverse a replace using a mapping table
  cleanlog Drop every line that contains a keyword (log sanitisation)

Keyword list format: one keyword per line, UTF-8, blank lines / # comments ignored.
"""
from __future__ import annotations

import argparse
import bisect
import json
import re
import shutil
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


# ── Keyword list loading ───────────────────────────────────────────────────────

def load_keywords(path: str) -> list[str]:
    """Load keywords from file; skip blank lines and # comments."""
    keywords = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            keywords.append(stripped)
    if not keywords:
        print("[warn] keyword file is empty", file=sys.stderr)
    return keywords


def sorted_keywords(keywords: list[str]) -> list[str]:
    """Return keywords sorted by length (longest first) to avoid partial masking."""
    return sorted(keywords, key=len, reverse=True)


def build_pattern(keywords: list[str], ignore_case: bool = False,
                  regex_mode: bool = False) -> re.Pattern:
    """Compile all keywords into one regex for efficient multi-keyword search."""
    if regex_mode:
        parts = [f"(?:{kw})" for kw in sorted_keywords(keywords)]
    else:
        parts = [re.escape(kw) for kw in sorted_keywords(keywords)]
    flags = re.IGNORECASE if ignore_case else 0
    try:
        return re.compile("|".join(parts), flags)
    except re.error as e:
        print(f"[error] invalid regex pattern: {e}", file=sys.stderr)
        sys.exit(1)


# ── File discovery ─────────────────────────────────────────────────────────────

def iter_files(target: str, recursive: bool, include_binary: bool) -> Iterator[Path]:
    root = Path(target)
    if root.is_file():
        if include_binary or not _is_binary(root):
            yield root
        return
    for p in (root.rglob("*") if recursive else root.iterdir()):
        if not p.is_file():
            continue
        if not include_binary and _is_binary(p):
            continue
        yield p


def _is_binary(path: Path) -> bool:
    """Heuristic: read first 8 KB and check for null bytes."""
    try:
        chunk = path.read_bytes()[:8192]
        return b"\x00" in chunk
    except OSError:
        return False


# ── Binary-search helpers (for sorted keyword lookups) ────────────────────────

def keyword_exists_bsearch(sorted_kws: list[str], keyword: str) -> bool:
    """O(log n) existence check on a sorted keyword list."""
    idx = bisect.bisect_left(sorted_kws, keyword)
    return idx < len(sorted_kws) and sorted_kws[idx] == keyword


# ── 1. SEARCH ─────────────────────────────────────────────────────────────────

@dataclass
class Match:
    file: str
    line: int      # 1-based
    col: int       # 1-based
    keyword: str
    context: str   # surrounding line text


def cmd_search(args: argparse.Namespace) -> None:
    keywords = load_keywords(args.keywords)
    if not keywords:
        return

    pattern = build_pattern(keywords, True, getattr(args, "regex", False))
    matches: list[Match] = []

    for fpath in iter_files(args.target, True, args.binary):
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"[skip] {fpath}: {e}", file=sys.stderr)
            continue

        for lineno, line in enumerate(text.splitlines(), start=1):
            for m in pattern.finditer(line):
                matches.append(
                    Match(
                        file=str(fpath),
                        line=lineno,
                        col=m.start() + 1,
                        keyword=m.group(0),
                        context=line.rstrip(),
                    )
                )

    if not matches:
        print("No keywords found.")
        return

    # Group output by file
    current_file = None
    for m in matches:
        if m.file != current_file:
            current_file = m.file
            print(f"\n{m.file}")
            print("-" * len(m.file))
        print(f"  line {m.line:>5}, col {m.col:>4}  [{m.keyword!r}]  {m.context}")

    print(f"\nTotal: {len(matches)} occurrence(s) across "
          f"{len({m.file for m in matches})} file(s).")

    if args.output:
        data = [
            {"file": m.file, "line": m.line, "col": m.col,
             "keyword": m.keyword, "context": m.context}
            for m in matches
        ]
        Path(args.output).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
        print(f"Results saved → {args.output}")


# ── 2. CLEAR ──────────────────────────────────────────────────────────────────

def cmd_clear(args: argparse.Namespace) -> None:
    keywords = load_keywords(args.keywords)
    if not keywords:
        return

    pattern = build_pattern(keywords, True, getattr(args, "regex", False))
    replacement = args.replacement  # default ""
    dry_run = getattr(args, "dry_run", False)

    changed = 0
    for fpath in iter_files(args.target, True, False):
        try:
            original = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"[skip] {fpath}: {e}", file=sys.stderr)
            continue

        new_text, n = pattern.subn(replacement, original)
        if n == 0:
            continue

        if dry_run:
            print(f"\n{fpath}  ({n} occurrence(s) would be cleared)")
            for lineno, line in enumerate(original.splitlines(), 1):
                if pattern.search(line):
                    new_line = pattern.sub(replacement, line)
                    print(f"  line {lineno:>4}  - {line.rstrip()}")
                    print(f"           + {new_line.rstrip()}")
            continue

        if args.backup:
            shutil.copy2(fpath, str(fpath) + ".bak")

        fpath.write_text(new_text, encoding="utf-8")
        print(f"  cleared {n:>4} occurrence(s)  {fpath}")
        changed += n

    if dry_run:
        return

    print(f"\nDone. Cleared {changed} occurrence(s) total.")


# ── 3. REPLACE ────────────────────────────────────────────────────────────────

def cmd_replace(args: argparse.Namespace) -> None:
    keywords = load_keywords(args.keywords)
    if not keywords:
        return

    dry_run = getattr(args, "dry_run", False)
    pattern = build_pattern(keywords, True, getattr(args, "regex", False))
    mapping: dict[str, str] = {}   # token -> canonical keyword
    changed_files = 0

    canonical: dict[str, str] = {kw.lower(): kw for kw in keywords}

    def make_token(matched: str) -> str:
        """Return a stable token per unique canonical keyword."""
        keyword = canonical.get(matched.lower(), matched)
        for tok, kw in mapping.items():
            if kw == keyword:
                return tok
        token = f"[[KW_{uuid.uuid4().hex[:8].upper()}]]"
        mapping[token] = keyword
        return token

    for fpath in iter_files(args.target, True, False):
        try:
            original = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"[skip] {fpath}: {e}", file=sys.stderr)
            continue

        def replacer(m: re.Match) -> str:
            return make_token(m.group(0))

        new_text, n = pattern.subn(replacer, original)
        if n == 0:
            continue

        if dry_run:
            print(f"\n{fpath}  ({n} occurrence(s) would be replaced)")
            for lineno, line in enumerate(original.splitlines(), 1):
                if pattern.search(line):
                    new_line = pattern.sub(replacer, line)
                    print(f"  line {lineno:>4}  - {line.rstrip()}")
                    print(f"           + {new_line.rstrip()}")
            continue

        if args.backup:
            shutil.copy2(fpath, str(fpath) + ".bak")

        fpath.write_text(new_text, encoding="utf-8")
        print(f"  replaced {n:>4} occurrence(s)  {fpath}")
        changed_files += 1

    if dry_run:
        return

    # Save mapping table
    mapping_path = Path(args.mapping)
    mapping_path.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nMapping table ({len(mapping)} token(s)) saved → {args.mapping}")
    print(f"Processed {changed_files} file(s).")


# ── 4. RESTORE ────────────────────────────────────────────────────────────────

def cmd_restore(args: argparse.Namespace) -> None:
    mapping_path = Path(args.mapping)
    if not mapping_path.exists():
        print(f"[error] mapping file not found: {args.mapping}", file=sys.stderr)
        sys.exit(1)

    mapping: dict[str, str] = json.loads(mapping_path.read_text(encoding="utf-8"))
    if not mapping:
        print("[warn] mapping table is empty.")
        return

    dry_run = getattr(args, "dry_run", False)
    # Build one regex that matches any token (tokens contain literal brackets)
    token_pattern = re.compile("|".join(re.escape(t) for t in mapping))
    changed_files = 0

    for fpath in iter_files(args.target, True, False):
        try:
            original = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"[skip] {fpath}: {e}", file=sys.stderr)
            continue

        def restore_token(m: re.Match) -> str:
            return mapping[m.group(0)]

        new_text, n = token_pattern.subn(restore_token, original)
        if n == 0:
            continue

        if dry_run:
            print(f"\n{fpath}  ({n} token(s) would be restored)")
            for lineno, line in enumerate(original.splitlines(), 1):
                if token_pattern.search(line):
                    new_line = token_pattern.sub(restore_token, line)
                    print(f"  line {lineno:>4}  - {line.rstrip()}")
                    print(f"           + {new_line.rstrip()}")
            continue

        if args.backup:
            shutil.copy2(fpath, str(fpath) + ".bak")

        fpath.write_text(new_text, encoding="utf-8")
        print(f"  restored {n:>4} token(s)  {fpath}")
        changed_files += 1

    if dry_run:
        return

    print(f"\nDone. Restored tokens in {changed_files} file(s).")


# ── 5. CLEANLOG ───────────────────────────────────────────────────────────────

def cmd_cleanlog(args: argparse.Namespace) -> None:
    keywords = load_keywords(args.keywords)
    if not keywords:
        return

    pattern = build_pattern(keywords, True, getattr(args, "regex", False))
    total_removed = 0
    total_kept = 0

    for fpath in iter_files(args.target, True, False):
        try:
            original = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"[skip] {fpath}: {e}", file=sys.stderr)
            continue

        lines = original.splitlines(keepends=True)
        kept, removed = [], []
        for line in lines:
            if pattern.search(line):
                removed.append(line)
            else:
                kept.append(line)

        if not removed:
            continue

        if args.dry_run:
            print(f"\n{fpath}  ({len(removed)} line(s) would be removed)")
            for ln in removed:
                print(f"  - {ln.rstrip()}")
            continue

        if args.backup:
            shutil.copy2(fpath, str(fpath) + ".bak")

        fpath.write_text("".join(kept), encoding="utf-8")
        total_removed += len(removed)
        total_kept += len(kept)

        if args.stats:
            pct = len(removed) / len(lines) * 100
            print(f"  {len(removed):>5} removed / {len(kept):>5} kept  ({pct:.1f}%)  {fpath}")
        else:
            print(f"  removed {len(removed):>5} line(s)  {fpath}")

    if args.dry_run:
        return

    if total_removed == 0:
        print("No matching lines found.")
    else:
        total_lines = total_removed + total_kept
        pct = total_removed / total_lines * 100 if total_lines else 0
        print(f"\nDone. Removed {total_removed} line(s) / kept {total_kept} ({pct:.1f}% stripped).")


# ── 6. REMAP ──────────────────────────────────────────────────────────────────

def load_remap(path: str) -> dict[str, str]:
    """Load remap pairs from file; format: 'original -> replacement'."""
    mapping: dict[str, str] = {}
    for lineno, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if " -> " not in stripped:
            print(f"[warn] line {lineno}: invalid remap entry (expected 'A -> B'): {stripped!r}",
                  file=sys.stderr)
            continue
        original, replacement = stripped.split(" -> ", 1)
        mapping[original.strip()] = replacement.strip()
    if not mapping:
        print("[warn] remap file is empty", file=sys.stderr)
    return mapping


def cmd_remap(args: argparse.Namespace) -> None:
    mapping = load_remap(args.remap)
    if not mapping:
        return

    originals = sorted(mapping.keys(), key=len, reverse=True)
    pattern = re.compile(b"|".join(re.escape(k.encode()) for k in originals), re.IGNORECASE)
    bytes_mapping = {k.lower().encode(): v.encode() for k, v in mapping.items()}
    total_changed = 0

    for fpath in iter_files(args.target, True, True):
        try:
            original_bytes = fpath.read_bytes()
        except OSError as e:
            print(f"[skip] {fpath}: {e}", file=sys.stderr)
            continue

        def replacer(m: re.Match) -> bytes:
            return bytes_mapping[m.group(0).lower()]

        new_bytes, n = pattern.subn(replacer, original_bytes)
        if n == 0:
            continue

        if args.dry_run:
            print(f"\n{fpath}  ({n} replacement(s) would be made)")
            for lineno, line in enumerate(original_bytes.splitlines(), 1):
                if pattern.search(line):
                    new_line = pattern.sub(replacer, line)
                    print(f"  line {lineno:>4}  - {line.decode(errors='replace').rstrip()}")
                    print(f"           + {new_line.decode(errors='replace').rstrip()}")
            continue

        if args.backup:
            shutil.copy2(fpath, str(fpath) + ".bak")

        fpath.write_bytes(new_bytes)
        print(f"  remapped {n:>4} value(s)  {fpath}")
        total_changed += n

    if args.dry_run:
        return

    if total_changed == 0:
        print("No matching values found.")
    else:
        print(f"\nDone. Remapped {total_changed} value(s) total.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Keyword filter toolkit for AI data preparation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="command", required=True)

    # shared flags
    def add_common(sp, need_keywords=True, need_target=True, need_backup=True,
                   need_dry_run=False, need_regex=False):
        if need_keywords:
            sp.add_argument("-k", "--keywords", required=True,
                            metavar="FILE", help="keyword list file (one per line)")
        if need_target:
            sp.add_argument("-t", "--target", required=True,
                            metavar="PATH", help="file or directory to process")
        if need_backup:
            sp.add_argument("--backup", action="store_true",
                            help="save .bak copy before modifying each file")
        if need_dry_run:
            sp.add_argument("--dry-run", action="store_true",
                            help="preview changes without modifying files")
        if need_regex:
            sp.add_argument("--regex", action="store_true",
                            help="treat each keyword line as a regex pattern")

    # search
    s1 = sub.add_parser("search", help="find all keyword occurrences")
    add_common(s1, need_backup=False, need_regex=True)
    s1.add_argument("--binary", action="store_true",
                    help="also search binary files")
    s1.add_argument("-o", "--output", metavar="JSON",
                    help="save results to JSON file")
    s1.set_defaults(func=cmd_search)

    # clear
    s2 = sub.add_parser("clear", help="erase keywords from files")
    add_common(s2, need_dry_run=True, need_regex=True)
    s2.add_argument("--replacement", default="",
                    help="string to replace keywords with (default: empty)")
    s2.set_defaults(func=cmd_clear)

    # replace
    s3 = sub.add_parser("replace", help="replace keywords with tokens")
    add_common(s3, need_dry_run=True, need_regex=True)
    s3.add_argument("-m", "--mapping", default="mapping.json",
                    metavar="JSON", help="output mapping table path (default: mapping.json)")
    s3.set_defaults(func=cmd_replace)

    # restore
    s4 = sub.add_parser("restore", help="restore tokens using mapping table")
    add_common(s4, need_keywords=False, need_dry_run=True)
    s4.add_argument("-m", "--mapping", default="mapping.json",
                    metavar="JSON", help="mapping table produced by replace (default: mapping.json)")
    s4.set_defaults(func=cmd_restore)

    # cleanlog
    s5 = sub.add_parser("cleanlog", help="drop every line containing a keyword")
    add_common(s5, need_regex=True)
    s5.add_argument("--dry-run", action="store_true",
                    help="preview which lines would be removed without modifying files")
    s5.add_argument("--stats", action="store_true",
                    help="show removed/kept counts and percentage per file")
    s5.set_defaults(func=cmd_cleanlog)

    # remap
    s6 = sub.add_parser("remap", help="replace values using a remap list (e.g. real IP → dummy IP)")
    add_common(s6, need_keywords=False)
    s6.add_argument("--remap", required=True, metavar="FILE",
                    help="remap list file (format: 'original -> replacement', one per line)")
    s6.add_argument("--dry-run", action="store_true",
                    help="preview replacements without modifying files")
    s6.set_defaults(func=cmd_remap)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
