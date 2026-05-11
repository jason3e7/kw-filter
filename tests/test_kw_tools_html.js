#!/usr/bin/env node
/**
 * Tests for the JS logic in kw_tools.html.
 * Covers buildPattern / opSearch / opClear / opReplace / opCleanlog
 * in both literal mode (regexMode=false) and regex mode (regexMode=true).
 *
 * Run: node tests/test_kw_tools_html.js
 */

'use strict';

// ── Functions copied from kw_tools.html (keep in sync) ───────────────────────

function escRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

function buildPattern(kws, regexMode = false) {
  const sorted = [...kws].filter(k => k.trim()).sort((a, b) => b.length - a.length);
  if (!sorted.length) return null;
  const parts = regexMode ? sorted.map(k => `(?:${k})`) : sorted.map(escRe);
  try {
    return new RegExp(parts.join('|'), 'gi');
  } catch (e) {
    return null;
  }
}

function opSearch(text, kws, regexMode = false) {
  const pat = buildPattern(kws, regexMode);
  if (!pat) return [];
  const results = [];
  text.split('\n').forEach((line, li) => {
    pat.lastIndex = 0;
    let m;
    while ((m = pat.exec(line)) !== null)
      results.push({ line: li + 1, col: m.index + 1, kw: m[0], ctx: line });
  });
  return results;
}

function opClear(text, kws, replacement, regexMode = false) {
  const pat = buildPattern(kws, regexMode);
  if (!pat) return { text, count: 0 };
  let count = 0;
  return { text: text.replace(pat, () => { count++; return replacement; }), count };
}

function opReplace(text, kws, regexMode = false) {
  const pat = buildPattern(kws, regexMode);
  if (!pat) return { text, mapping: {} };
  const canonical = {};
  kws.forEach(k => canonical[k.toLowerCase()] = k);
  const mapping = {}, kwToTok = {};
  let seq = 0;
  const out = text.replace(pat, m => {
    const kw = canonical[m.toLowerCase()] || m;
    if (kwToTok[kw]) return kwToTok[kw];
    const tok = `[[KW_${String(++seq).padStart(8, '0')}]]`;
    kwToTok[kw] = tok; mapping[tok] = kw;
    return tok;
  });
  return { text: out, mapping };
}

function opCleanlog(text, kws, regexMode = false) {
  const pat = buildPattern(kws, regexMode);
  if (!pat) return { text, removed: 0, kept: 0 };
  const lines = text.split('\n');
  const kept = []; let removed = 0;
  lines.forEach(l => { pat.lastIndex = 0; pat.test(l) ? removed++ : kept.push(l); });
  return { text: kept.join('\n'), removed, kept: kept.length };
}

// ── Test runner ───────────────────────────────────────────────────────────────

let passed = 0, failed = 0;
const TOKEN_RE = /\[\[KW_\d{8}\]\]/;

function test(name, fn) {
  try {
    fn();
    console.log(`  ✓  ${name}`);
    passed++;
  } catch (e) {
    console.log(`  ✗  ${name}`);
    console.log(`     ${e.message}`);
    failed++;
  }
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg || 'assertion failed');
}

function assertEqual(a, b, msg) {
  if (a !== b) throw new Error(msg || `expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`);
}

// ── buildPattern ──────────────────────────────────────────────────────────────

console.log('\nbuildPattern');

test('literal: empty list returns null', () => {
  assert(buildPattern([], false) === null);
});

test('literal: special chars are escaped', () => {
  const pat = buildPattern(['1.2.3.4'], false);
  assert(!pat.test('1X2X3X4'), 'dot should be escaped');
  assert(pat.test('1.2.3.4'), 'exact match should work');
});

test('regex: pattern is used as-is', () => {
  const pat = buildPattern(['\\d+\\.\\d+\\.\\d+\\.\\d+'], true);
  // g flag makes lastIndex stateful — reset before each standalone test()
  pat.lastIndex = 0; assert(pat.test('10.0.0.1'), 'should match 10.0.0.1');
  pat.lastIndex = 0; assert(pat.test('192.168.1.100'), 'should match 192.168.1.100');
  pat.lastIndex = 0; assert(!pat.test('hello'), 'should not match hello');
});

test('regex: invalid pattern returns null', () => {
  assert(buildPattern(['[invalid'], true) === null);
});

test('regex: multiple patterns combined', () => {
  const pat = buildPattern(['\\d{4}', '[a-z]+@[a-z]+\\.com'], true);
  assert(pat.test('2024'));
  assert(pat.test('alice@corp.com'));
});

// ── opSearch ─────────────────────────────────────────────────────────────────

console.log('\nopSearch');

test('literal: finds exact keyword', () => {
  const r = opSearch('hello john doe\nno match here', ['john doe'], false);
  assertEqual(r.length, 1);
  assertEqual(r[0].line, 1);
  assertEqual(r[0].kw.toLowerCase(), 'john doe');
});

test('literal: case-insensitive match', () => {
  const r = opSearch('Hello JOHN DOE', ['john doe'], false);
  assertEqual(r.length, 1);
});

test('literal: dot in keyword not treated as wildcard', () => {
  const r = opSearch('1X2X3X4', ['1.2.3.4'], false);
  assertEqual(r.length, 0);
});

test('regex: IP pattern matches multiple IPs', () => {
  const r = opSearch('10.0.0.1\n192.168.1.1\nnot-an-ip', ['\\d+\\.\\d+\\.\\d+\\.\\d+'], true);
  assertEqual(r.length, 2);
  assertEqual(r[0].kw, '10.0.0.1');
  assertEqual(r[1].kw, '192.168.1.1');
});

test('regex: no matches returns empty array', () => {
  const r = opSearch('hello world', ['\\d{4}'], true);
  assertEqual(r.length, 0);
});

// ── opClear ───────────────────────────────────────────────────────────────────

console.log('\nopClear');

test('literal: replaces keyword with empty string', () => {
  const r = opClear('foo bar foo', ['foo'], '', false);
  assertEqual(r.text, ' bar ');
  assertEqual(r.count, 2);
});

test('literal: replaces keyword with custom text', () => {
  const r = opClear('secret value here', ['secret'], '[REDACTED]', false);
  assertEqual(r.text, '[REDACTED] value here');
  assertEqual(r.count, 1);
});

test('literal: no match returns original text', () => {
  const r = opClear('hello world', ['xyz'], '', false);
  assertEqual(r.text, 'hello world');
  assertEqual(r.count, 0);
});

test('regex: pattern clears all matches', () => {
  const r = opClear('server 10.0.0.1 and 192.168.1.1', ['\\d+\\.\\d+\\.\\d+\\.\\d+'], '[IP]', true);
  assertEqual(r.text, 'server [IP] and [IP]');
  assertEqual(r.count, 2);
});

// ── opReplace ─────────────────────────────────────────────────────────────────

console.log('\nopReplace');

test('literal: keyword replaced with token', () => {
  const r = opReplace('hello alice goodbye alice', ['alice'], false);
  assert(!r.text.includes('alice'));
  assert(TOKEN_RE.test(r.text));
});

test('literal: same keyword reuses same token', () => {
  const r = opReplace('alice and alice', ['alice'], false);
  const tokens = r.text.match(/\[\[KW_\d{8}\]\]/g);
  assertEqual(tokens[0], tokens[1], 'same keyword should produce same token');
  assertEqual(Object.keys(r.mapping).length, 1);
});

test('literal: mapping stores original value', () => {
  const r = opReplace('Alice is here', ['Alice'], false);
  const tok = Object.keys(r.mapping)[0];
  assertEqual(r.mapping[tok], 'Alice');
});

test('literal: case-insensitive — ALICE and alice share one token', () => {
  const r = opReplace('ALICE met alice', ['alice'], false);
  const tokens = r.text.match(/\[\[KW_\d{8}\]\]/g);
  assertEqual(tokens[0], tokens[1]);
  assertEqual(Object.keys(r.mapping).length, 1);
});

test('regex: different matched values get different tokens', () => {
  const r = opReplace('10.0.0.1 and 192.168.1.1', ['\\d+\\.\\d+\\.\\d+\\.\\d+'], true);
  assertEqual(Object.keys(r.mapping).length, 2);
  const vals = Object.values(r.mapping);
  assert(vals.includes('10.0.0.1'), 'mapping should contain 10.0.0.1');
  assert(vals.includes('192.168.1.1'), 'mapping should contain 192.168.1.1');
});

test('regex: same matched value reuses token', () => {
  const r = opReplace('10.0.0.1 again 10.0.0.1', ['\\d+\\.\\d+\\.\\d+\\.\\d+'], true);
  assertEqual(Object.keys(r.mapping).length, 1);
  const tokens = r.text.match(/\[\[KW_\d{8}\]\]/g);
  assertEqual(tokens[0], tokens[1]);
});

test('regex: mapping values are actual matched strings not patterns', () => {
  const r = opReplace('call 123-4567 or 987-6543', ['\\d{3}-\\d{4}'], true);
  const vals = Object.values(r.mapping);
  assert(vals.includes('123-4567'));
  assert(vals.includes('987-6543'));
});

test('regex: no match returns empty mapping', () => {
  const r = opReplace('hello world', ['\\d{4}'], true);
  assertEqual(Object.keys(r.mapping).length, 0);
  assertEqual(r.text, 'hello world');
});

// ── opCleanlog ────────────────────────────────────────────────────────────────

console.log('\nopCleanlog');

test('literal: removes lines containing keyword', () => {
  const r = opCleanlog('keep this\nremove secret here\nkeep too', ['secret'], false);
  assertEqual(r.removed, 1);
  assertEqual(r.kept, 2);
  assert(!r.text.includes('secret'));
});

test('literal: no match keeps all lines', () => {
  const r = opCleanlog('line1\nline2', ['xyz'], false);
  assertEqual(r.removed, 0);
  assertEqual(r.kept, 2);
});

test('regex: removes lines matching pattern', () => {
  const lines = '192.168.1.1 connected\nnormal log line\n10.0.0.1 accessed';
  const r = opCleanlog(lines, ['\\d+\\.\\d+\\.\\d+\\.\\d+'], true);
  assertEqual(r.removed, 2);
  assertEqual(r.kept, 1);
  assert(r.text.includes('normal log line'));
});

// ── Demo scenario: server inventory (demo_regex_ip/) ─────────────────────────
// Input / expected outputs correspond to files in tests/demo_regex_ip/

console.log('\ndemo_regex_ip scenario');

const DEMO_INPUT = [
  '# Server inventory',
  'server 127.0.0.1 role=web',
  'server 127.0.0.2 role=web',
  'server 10.0.0.1  role=db',
  'server 10.0.0.2  role=db',
  'server 192.168.1.100 role=cache',
  '# Firewall rules',
  'allow 127.0.0.1 -> 10.0.0.1 port=5432',
  'allow 127.0.0.2 -> 10.0.0.2 port=5432',
  'deny 0.0.0.0/0',
].join('\n');

const DEMO_KWS   = ['\\d+\\.\\d+\\.\\d+\\.\\d+'];
const DEMO_RXMODE = true;

test('demo: search finds 10 IP occurrences across 8 lines', () => {
  const matches = opSearch(DEMO_INPUT, DEMO_KWS, DEMO_RXMODE);
  assertEqual(matches.length, 10);
  // unique IPs matched
  const unique = [...new Set(matches.map(m => m.kw))];
  assertEqual(unique.length, 6, 'should find 6 distinct IPs');
});

test('demo: search line numbers are correct', () => {
  const matches = opSearch(DEMO_INPUT, DEMO_KWS, DEMO_RXMODE);
  // first match is 127.0.0.1 on line 2
  assertEqual(matches[0].line, 2);
  assertEqual(matches[0].kw,   '127.0.0.1');
  // last match is 0.0.0.0 on line 10
  assertEqual(matches[matches.length - 1].line, 10);
  assertEqual(matches[matches.length - 1].kw,   '0.0.0.0');
});

test('demo: replace produces 6 unique tokens for 6 distinct IPs', () => {
  const r = opReplace(DEMO_INPUT, DEMO_KWS, DEMO_RXMODE);
  assertEqual(Object.keys(r.mapping).length, 6);
  const vals = Object.values(r.mapping);
  for (const ip of ['127.0.0.1','127.0.0.2','10.0.0.1','10.0.0.2','192.168.1.100','0.0.0.0'])
    assert(vals.includes(ip), `mapping missing ${ip}`);
});

test('demo: replace reuses token for repeated IP (127.0.0.1 appears twice)', () => {
  const r = opReplace(DEMO_INPUT, DEMO_KWS, DEMO_RXMODE);
  // 127.0.0.1 appears on line 2 and line 8 — both should use same token
  const tok = Object.keys(r.mapping).find(t => r.mapping[t] === '127.0.0.1');
  const count = (r.text.match(new RegExp(tok.replace(/[[\]]/g,'\\$&'), 'g')) || []).length;
  assertEqual(count, 2, '127.0.0.1 token should appear twice');
});

test('demo: replace output contains no raw IPs', () => {
  const r = opReplace(DEMO_INPUT, DEMO_KWS, DEMO_RXMODE);
  const ipPat = /\d+\.\d+\.\d+\.\d+/;
  assert(!ipPat.test(r.text), 'replace output should contain no raw IPs');
});

test('demo: cleanlog removes 8 lines with IPs, keeps 2 comment lines', () => {
  const r = opCleanlog(DEMO_INPUT, DEMO_KWS, DEMO_RXMODE);
  assertEqual(r.removed, 8);
  assertEqual(r.kept,    2);   // "# Server inventory" + "# Firewall rules"
  assert(r.text.includes('# Server inventory'));
  assert(r.text.includes('# Firewall rules'));
  assert(!r.text.includes('127.0.0'));
});

// ── Summary ───────────────────────────────────────────────────────────────────

console.log(`\n${'─'.repeat(40)}`);
console.log(`  ${passed + failed} tests: ${passed} passed, ${failed} failed`);
if (failed > 0) {
  console.log('  FAIL');
  process.exit(1);
} else {
  console.log('  PASS');
}
