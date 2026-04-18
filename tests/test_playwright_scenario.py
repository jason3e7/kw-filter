"""
Integration test: scraper output → keyword filtering → AI Playwright generation.

Scenario
--------
A QA engineer scrapes an internal login page to collect form structure, test
credentials, and environment details. Before handing the data to an AI (to
generate a Playwright test), all sensitive values are tokenised with kw-filter.
The AI writes Playwright code using the safe tokens. kw-filter then restores
the originals so the final script is ready to run.

Workflow
--------
1. scrape_output.txt  (contains real credentials / IPs)
        │
        ▼  kw-filter replace
2. scrape_tokenised.txt  ([[KW_XXXX]] everywhere)
        │
        ▼  send to AI (simulated here by _ai_generate_playwright)
3. playwright_tokens.py  (Playwright code with tokens)
        │
        ▼  kw-filter restore
4. playwright_final.py  (working script with real values)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from kw_tools import cmd_replace, cmd_restore
from conftest import ns_replace, ns_restore

# ── Fixtures ──────────────────────────────────────────────────────────────────

SCRAPE_OUTPUT = """\
=== Login Page Analysis ===
URL: https://crm.acme-internal.com/login
Scraped: 2024-01-15 09:30:00

Form fields:
  - #email     (type: email, placeholder: "Work email")
  - #password  (type: password)
  - #submit    (type: submit, text: "Sign In")

Test credentials (staging env):
  Admin : admin@acme-internal.com / Admin2024!
  User  : bob.chen@acme.com       / UserPass123

Post-login redirect: https://crm.acme-internal.com/dashboard

Notes:
  - Rate limit: 5 attempts / minute per IP
  - Internal proxy: 10.0.1.55:8080
  - Staging API key: sk-test-7f8d9e2a1b3c
"""

KEYWORDS = """\
admin@acme-internal.com
Admin2024!
bob.chen@acme.com
UserPass123
acme-internal.com
10.0.1.55
sk-test-7f8d9e2a1b3c
"""

SENSITIVE_VALUES = [
    "admin@acme-internal.com",
    "Admin2024!",
    "bob.chen@acme.com",
    "UserPass123",
    "acme-internal.com",
    "10.0.1.55",
    "sk-test-7f8d9e2a1b3c",
]


def _ai_generate_playwright(tokenised_context: str) -> str:
    """Simulate what an AI returns when given the tokenised scraper output.

    In a real workflow this would be an API call to Claude / GPT.  Here we
    hard-code a realistic Playwright script that references every token that
    appeared in the input, so the test can verify end-to-end restore.
    """
    # Extract tokens from the context so the simulated AI uses the exact
    # tokens produced by this specific replace run (token values are random).
    tokens = re.findall(r'\[\[KW_[0-9A-F]{8}\]\]', tokenised_context)
    unique_tokens = list(dict.fromkeys(tokens))   # preserve order, deduplicate

    # Map positional tokens to role names so generated code is readable.
    # The replace command processes keywords in longest-first order, so the
    # token assignment order follows keyword length descending.
    t = {i: tok for i, tok in enumerate(unique_tokens)}

    lines = [
        "import { test, expect } from '@playwright/test';",
        "",
        "test('admin login and dashboard redirect', async ({ page }) => {",
        f"  await page.goto('https://crm.{t.get(4, '[TOKEN_DOMAIN]')}/login');",
        "",
        f"  // Fill admin credentials",
        f"  await page.fill('#email',    '{t.get(0, '[TOKEN_EMAIL]')}');",
        f"  await page.fill('#password', '{t.get(1, '[TOKEN_PASS]')}');",
        "  await page.click('#submit');",
        "",
        f"  await expect(page).toHaveURL('https://crm.{t.get(4, '[TOKEN_DOMAIN]')}/dashboard');",
        "});",
        "",
        "test('regular user login', async ({ page }) => {",
        f"  await page.goto('https://crm.{t.get(4, '[TOKEN_DOMAIN]')}/login');",
        f"  await page.fill('#email',    '{t.get(2, '[TOKEN_EMAIL2]')}');",
        f"  await page.fill('#password', '{t.get(3, '[TOKEN_PASS2]')}');",
        "  await page.click('#submit');",
        "",
        f"  await expect(page).toHaveURL('https://crm.{t.get(4, '[TOKEN_DOMAIN]')}/dashboard');",
        "});",
        "",
        "// Config",
        f"// API key: {t.get(6, '[TOKEN_KEY]')}",
        f"// Proxy:   {t.get(5, '[TOKEN_IP]')}:8080",
    ]
    return "\n".join(lines) + "\n"


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestPlaywrightWorkflow:
    def _setup(self, tmp_path):
        scrape = tmp_path / "scrape_output.txt"
        scrape.write_text(SCRAPE_OUTPUT, encoding="utf-8")
        kw = tmp_path / "keywords.txt"
        kw.write_text(KEYWORDS, encoding="utf-8")
        mapping = tmp_path / "mapping.json"
        return scrape, kw, mapping

    def test_step1_replace_removes_all_sensitive_values(self, tmp_path):
        scrape, kw, mapping = self._setup(tmp_path)
        cmd_replace(ns_replace(kw, scrape, mapping))
        tokenised = scrape.read_text(encoding="utf-8")
        for val in SENSITIVE_VALUES:
            assert val.lower() not in tokenised.lower(), \
                f"Sensitive value still present after replace: {val!r}"
        assert "[[KW_" in tokenised

    def test_step1_mapping_contains_all_keywords(self, tmp_path):
        scrape, kw, mapping = self._setup(tmp_path)
        cmd_replace(ns_replace(kw, scrape, mapping))
        m = json.loads(mapping.read_text(encoding="utf-8"))
        canonical_values = {v.lower() for v in m.values()}
        for val in SENSITIVE_VALUES:
            assert val.lower() in canonical_values, \
                f"Keyword missing from mapping: {val!r}"

    def test_step2_ai_output_uses_tokens(self, tmp_path):
        scrape, kw, mapping = self._setup(tmp_path)
        cmd_replace(ns_replace(kw, scrape, mapping))
        tokenised = scrape.read_text(encoding="utf-8")

        pw_code = _ai_generate_playwright(tokenised)
        assert "[[KW_" in pw_code, "AI output should contain tokens"
        for val in SENSITIVE_VALUES:
            assert val.lower() not in pw_code.lower(), \
                f"Real value leaked into AI output: {val!r}"

    def test_step3_restore_recovers_real_values(self, tmp_path):
        scrape, kw, mapping = self._setup(tmp_path)
        cmd_replace(ns_replace(kw, scrape, mapping))
        tokenised = scrape.read_text(encoding="utf-8")

        pw_tokens = tmp_path / "test_login_tokens.ts"
        pw_tokens.write_text(_ai_generate_playwright(tokenised), encoding="utf-8")

        cmd_restore(ns_restore(mapping, pw_tokens))
        restored = pw_tokens.read_text(encoding="utf-8")

        assert "acme-internal.com" in restored
        assert "admin@acme-internal.com" in restored
        assert "Admin2024!" in restored
        assert "[[KW_" not in restored

    def test_full_roundtrip_no_token_leakage(self, tmp_path):
        """Complete workflow: original scrape content is fully reconstructed."""
        scrape, kw, mapping = self._setup(tmp_path)
        original_scrape = scrape.read_text(encoding="utf-8")

        # Replace
        cmd_replace(ns_replace(kw, scrape, mapping))
        tokenised = scrape.read_text(encoding="utf-8")

        # Simulate AI step
        pw_tokens = tmp_path / "pw.ts"
        pw_tokens.write_text(_ai_generate_playwright(tokenised), encoding="utf-8")

        # Restore AI output
        cmd_restore(ns_restore(mapping, pw_tokens))
        final = pw_tokens.read_text(encoding="utf-8")

        # No tokens left anywhere
        assert "[[KW_" not in final
        # Restore the original scrape to verify mapping is correct
        cmd_restore(ns_restore(mapping, scrape))
        assert scrape.read_text(encoding="utf-8") == original_scrape


class TestPlaywrightExampleFiles:
    """Verify the committed example files work with the full workflow."""

    EXAMPLES_DIR = Path(__file__).parent.parent / "examples" / "playwright"

    def test_example_files_exist(self):
        assert (self.EXAMPLES_DIR / "keywords.txt").exists()
        assert (self.EXAMPLES_DIR / "scrape_output.txt").exists()

    def test_example_workflow(self, tmp_path):
        import shutil
        scrape = tmp_path / "scrape_output.txt"
        kw = tmp_path / "keywords.txt"
        mapping = tmp_path / "mapping.json"
        shutil.copy(self.EXAMPLES_DIR / "scrape_output.txt", scrape)
        shutil.copy(self.EXAMPLES_DIR / "keywords.txt", kw)

        cmd_replace(ns_replace(kw, scrape, mapping))
        tokenised = scrape.read_text(encoding="utf-8")

        assert "admin@acme-internal.com" not in tokenised
        assert "Admin2024!" not in tokenised
        assert "[[KW_" in tokenised

        cmd_restore(ns_restore(mapping, scrape))
        assert "admin@acme-internal.com" in scrape.read_text(encoding="utf-8")
