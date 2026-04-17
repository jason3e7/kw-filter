"""End-to-end CLI integration tests via subprocess."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = str(Path(__file__).parent.parent / "kw_tools.py")


def run(*args, expect_ok=True):
    result = subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True,
        text=True,
    )
    if expect_ok:
        assert result.returncode == 0, result.stderr
    return result


@pytest.fixture
def workspace(tmp_path):
    kw = tmp_path / "keywords.txt"
    kw.write_text("John Doe\nAcme Corp\nsecret_token\n", encoding="utf-8")

    data = tmp_path / "data"
    data.mkdir()
    (data / "report.txt").write_text(
        "Author: John Doe\nOrg: Acme Corp\nKey: secret_token\n",
        encoding="utf-8",
    )
    (data / "notes.txt").write_text(
        "Reminder: contact John Doe at Acme Corp.\n",
        encoding="utf-8",
    )
    (data / "unrelated.txt").write_text(
        "Nothing sensitive here.\n",
        encoding="utf-8",
    )
    return tmp_path


class TestCLISearch:
    def test_search_exits_zero(self, workspace):
        run("search", "-k", str(workspace / "keywords.txt"),
            "-t", str(workspace / "data"), "-r")

    def test_search_output_contains_keyword(self, workspace):
        r = run("search", "-k", str(workspace / "keywords.txt"),
                "-t", str(workspace / "data"), "-r")
        assert "John Doe" in r.stdout

    def test_search_json_output(self, workspace):
        out_json = workspace / "results.json"
        run("search", "-k", str(workspace / "keywords.txt"),
            "-t", str(workspace / "data"), "-r",
            "-o", str(out_json))
        assert out_json.exists()
        data = json.loads(out_json.read_text())
        assert isinstance(data, list)
        assert len(data) > 0

    def test_search_no_match(self, workspace):
        (workspace / "nope.txt").write_text("ZZZNOTHERE\n", encoding="utf-8")
        kf = workspace / "empty_kw.txt"
        kf.write_text("ZZZNOTHERE\n", encoding="utf-8")
        r = run("search", "-k", str(kf), "-t", str(workspace / "data"))
        assert "No keywords found" in r.stdout


class TestCLIClear:
    def test_clear_removes_keywords(self, workspace):
        run("clear", "-k", str(workspace / "keywords.txt"),
            "-t", str(workspace / "data"), "-r")

        text = (workspace / "data" / "report.txt").read_text(encoding="utf-8")
        assert "John Doe" not in text
        assert "Acme Corp" not in text

    def test_clear_with_replacement(self, workspace):
        run("clear", "-k", str(workspace / "keywords.txt"),
            "-t", str(workspace / "data"), "-r",
            "--replacement", "[REMOVED]")

        text = (workspace / "data" / "report.txt").read_text(encoding="utf-8")
        assert "[REMOVED]" in text

    def test_clear_backup(self, workspace):
        run("clear", "-k", str(workspace / "keywords.txt"),
            "-t", str(workspace / "data"), "-r", "--backup")

        assert (workspace / "data" / "report.txt.bak").exists()


class TestCLIReplace:
    def test_replace_creates_mapping(self, workspace):
        mp = workspace / "mapping.json"
        run("replace", "-k", str(workspace / "keywords.txt"),
            "-t", str(workspace / "data"), "-r",
            "-m", str(mp))

        assert mp.exists()
        mapping = json.loads(mp.read_text())
        assert "John Doe" in mapping.values()
        assert "Acme Corp" in mapping.values()

    def test_replace_tokenises_files(self, workspace):
        mp = workspace / "mapping.json"
        run("replace", "-k", str(workspace / "keywords.txt"),
            "-t", str(workspace / "data"), "-r",
            "-m", str(mp))

        text = (workspace / "data" / "report.txt").read_text(encoding="utf-8")
        assert "John Doe" not in text
        assert "[[KW_" in text


class TestCLIRestore:
    def test_restore_returns_original(self, workspace):
        mp = workspace / "mapping.json"
        originals = {
            p.name: p.read_text(encoding="utf-8")
            for p in (workspace / "data").iterdir()
            if p.is_file()
        }

        run("replace", "-k", str(workspace / "keywords.txt"),
            "-t", str(workspace / "data"), "-r", "-m", str(mp))
        run("restore", "-m", str(mp),
            "-t", str(workspace / "data"), "-r")

        for name, original in originals.items():
            restored = (workspace / "data" / name).read_text(encoding="utf-8")
            assert restored == original, f"Mismatch in {name}"

    def test_restore_missing_mapping_nonzero_exit(self, workspace):
        r = run("restore", "-m", str(workspace / "no_such.json"),
                "-t", str(workspace / "data"), expect_ok=False)
        assert r.returncode != 0


class TestCLIHelp:
    def test_help_exits_zero(self):
        run("--help", expect_ok=True)

    def test_subcommand_help(self):
        for sub in ("search", "clear", "replace", "restore"):
            run(sub, "--help")

    def test_no_subcommand_nonzero(self):
        r = run(expect_ok=False)
        assert r.returncode != 0
