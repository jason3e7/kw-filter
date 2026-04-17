# kw-filter

A CLI toolkit for filtering sensitive keywords from files before sending them to AI, and restoring them afterwards.

## Features

| Command | Description |
|---|---|
| `search` | Find all keyword occurrences — reports file, line, column |
| `clear` | Erase keywords in-place (replace with empty string or custom text) |
| `replace` | Replace keywords with anonymous tokens and emit a mapping table |
| `restore` | Use the mapping table to put original values back |

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
python3 kw_tools.py clear -k keywords.txt -t ./data -r --backup   # save .bak before editing
```

### 3. Replace — tokenise + generate mapping table

```bash
python3 kw_tools.py replace -k keywords.txt -t ./data -r -m mapping.json
```

Each keyword is replaced with a unique token like `[[KW_3F9A1C2D]]`.  
The same keyword always maps to the same token across all files.

`mapping.json`:
```json
{
  "[[KW_3F9A1C2D]]": "John Doe",
  "[[KW_88B1A39E]]": "Acme Corp"
}
```

### 4. Restore — put originals back

```bash
python3 kw_tools.py restore -m mapping.json -t ./data -r
```

Does not require the keyword list — only the mapping table.

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
| `-k FILE` | search, clear, replace | Keyword list file |
| `-t PATH` | all | Target file or directory |
| `-r` | all | Recurse into subdirectories |
| `-m FILE` | replace, restore | Mapping table JSON path |
| `--backup` | clear, replace, restore | Save `.bak` copy before modifying |
| `--replacement TEXT` | clear | Fill string instead of empty (default: `""`) |
| `-o FILE` | search | Save search results as JSON |

## Running tests

```bash
python3 -m pytest tests/ -v
```

93 tests covering:
- Unit tests for all helper functions (`test_utils.py`)
- Per-command tests with edge cases (`test_search/clear/replace/restore.py`)
- End-to-end CLI integration tests via subprocess (`test_integration.py`)

## Design notes

- **Longest-keyword-first matching**: keywords are sorted by length (descending) before being compiled into a single regex, so `John Doe` is matched before `John`.
- **Stable tokens**: the same keyword always produces the same token within a single `replace` run, across all files.
- **Binary file detection**: files containing null bytes are skipped unless `--binary` is passed (search only).
- **Binary search**: `bisect` is used for O(log n) keyword existence checks on sorted keyword lists.
