# kw-filter

A CLI toolkit for filtering sensitive keywords from files before sending them to AI, and restoring them afterwards.

## Features

| Command | Description |
|---|---|
| `search` | Find all keyword occurrences — reports file, line, column |
| `clear` | Erase keywords in-place (replace with empty string or custom text) |
| `replace` | Replace keywords with anonymous tokens and emit a mapping table |
| `restore` | Use the mapping table to put original values back |
| `cleanlog` | Drop every line that contains a keyword (log sanitisation) |
| `remap` | Replace values using an explicit mapping list (e.g. real IP → dummy IP) |

Each command is fully independent and can be run on its own.

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/kw-filter.git
cd kw-filter
pip install -r requirements.txt   # only needed to run tests
```

No third-party runtime dependencies — only the Python standard library.

## Keyword file format

One keyword per line. Blank lines and `#` comments are ignored.

```
# keywords.txt
John Doe
jane.doe@example.com
Acme Corp
secret_token_xyz
```

## Usage

### 1. Search — find occurrences

```bash
python3 kw_tools.py search -k keywords.txt -t ./data -r
python3 kw_tools.py search -k keywords.txt -t ./data -r -i   # case-insensitive
```

Output:
```
data/report.txt
---------------
  line     1, col    9  ['John Doe']  Author: John Doe
  line     2, col   10  ['Acme Corp']  Org: Acme Corp

Total: 2 occurrence(s) across 1 file(s).
```

Save results to JSON:
```bash
python3 kw_tools.py search -k keywords.txt -t ./data -r -o results.json
```

### 2. Clear — erase keywords

```bash
python3 kw_tools.py clear -k keywords.txt -t ./data -r
python3 kw_tools.py clear -k keywords.txt -t ./data -r --replacement "[REDACTED]"
python3 kw_tools.py clear -k keywords.txt -t ./data -r --backup     # save .bak before editing
python3 kw_tools.py clear -k keywords.txt -t ./data -r --dry-run    # preview changes
python3 kw_tools.py clear -k keywords.txt -t ./data -r -i           # case-insensitive
```

### 3. Replace — tokenise + generate mapping table

```bash
python3 kw_tools.py replace -k keywords.txt -t ./data -r
python3 kw_tools.py replace -k keywords.txt -t ./data -r -m custom.json  # custom mapping path
python3 kw_tools.py replace -k keywords.txt -t ./data -r -i             # case-insensitive
```

Each keyword is replaced with a unique token like `[[KW_3F9A1C2D]]`.  
The same keyword always maps to the same token across all files.  
`-m/--mapping` defaults to `mapping.json` if not specified.

`mapping.json`:
```json
{
  "[[KW_3F9A1C2D]]": "John Doe",
  "[[KW_88B1A39E]]": "Acme Corp"
}
```

When `-i` is used, all case variants (`john doe`, `JOHN DOE`) map to the same token using the canonical form from the keyword file.

### 4. Restore — put originals back

```bash
python3 kw_tools.py restore -t ./data -r
python3 kw_tools.py restore -m custom.json -t ./data -r  # custom mapping path
python3 kw_tools.py restore -m mapping.json -t ./data -r --dry-run  # preview
```

Does not require the keyword list — only the mapping table.  
`-m/--mapping` defaults to `mapping.json` if not specified.

### 5. Cleanlog — drop sensitive log lines

```bash
python3 kw_tools.py cleanlog -k keywords.txt -t ./logs -r
python3 kw_tools.py cleanlog -k keywords.txt -t app.log --dry-run   # preview
python3 kw_tools.py cleanlog -k keywords.txt -t ./logs -r --stats   # show %
python3 kw_tools.py cleanlog -k keywords.txt -t app.log --backup    # keep .bak
python3 kw_tools.py cleanlog -k keywords.txt -t app.log -i          # case-insensitive
```

Unlike `clear` (which removes only the matched text), `cleanlog` removes the **entire line** whenever a keyword appears anywhere on it. Designed for log files where a partial redaction is not sufficient.

### 6. Remap — replace with explicit values

```bash
python3 kw_tools.py remap --remap remap.txt -t ./logs -r
python3 kw_tools.py remap --remap remap.txt -t app.log --dry-run   # preview
python3 kw_tools.py remap --remap remap.txt -t ./logs -r --backup
python3 kw_tools.py remap --remap remap.txt -t ./logs -r -i        # case-insensitive
```

**Remap file format** — one `original -> replacement` pair per line:

```
# remap.txt
192.168.1.100 -> 127.0.0.1
alice@corp.com -> user@example.com
prod-db.internal -> test-db
```

Unlike `replace` (which generates random tokens), `remap` lets you specify the exact replacement value — useful for substituting real IPs, hostnames, or emails with plausible-looking fake values before sharing logs.

`remap` operates in **binary mode**: it reads and writes files as raw bytes, so it works on any file type (log files, compiled configs, binary blobs).

## Typical workflow

```bash
# 1. Check what will be affected
python3 kw_tools.py search -k keywords.txt -t ./docs -r

# 2. Replace before sending to AI
python3 kw_tools.py replace -k keywords.txt -t ./docs -r -m mapping.json --backup

# 3. Send tokenised files to AI ...

# 4. Restore originals in the AI output
python3 kw_tools.py restore -m mapping.json -t ./ai_output -r
```

## Common flags

| Flag | Commands | Description |
|---|---|---|
| `-k FILE` | search, clear, replace, cleanlog | Keyword list file |
| `-t PATH` | all | Target file or directory |
| `-r` | all | Recurse into subdirectories |
| `-m FILE` | replace, restore | Mapping table JSON path (default: `mapping.json`) |
| `--backup` | clear, replace, restore, remap | Save `.bak` copy before modifying |
| `--replacement TEXT` | clear | Fill string instead of empty (default: `""`) |
| `-o FILE` | search | Save search results as JSON |
| `--dry-run` | clear, replace, restore, cleanlog, remap | Preview changes without modifying files |
| `-i, --ignore-case` | search, clear, replace, cleanlog, remap | Match keywords case-insensitively |
| `--stats` | cleanlog | Show removed/kept count and percentage per file |
| `--remap FILE` | remap | Remap list file (`original -> replacement`) |

## Running tests

```bash
python3 -m pytest tests/ -v
```

161 tests covering:
- Unit tests for all helper functions (`test_utils.py`)
- Per-command tests with edge cases (`test_search/clear/replace/restore/remap/cleanlog.py`)
- Cross-command tests for `--dry-run` and `-i/--ignore-case` (`test_dry_run_ignore_case.py`)
- End-to-end CLI integration tests via subprocess (`test_integration.py`)

## Design notes

- **Longest-keyword-first matching**: keywords are sorted by length (descending) before being compiled into a single regex, so `John Doe` is matched before `John`.
- **Stable tokens**: the same keyword always produces the same token within a single `replace` run, across all files.
- **Binary file detection**: files containing null bytes are skipped unless `--binary` is passed (search only).
- **Binary search**: `bisect` is used for O(log n) keyword existence checks on sorted keyword lists.
