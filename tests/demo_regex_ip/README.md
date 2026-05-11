# Demo：Regex 模式 — 自動偵測並替換 IP 位址

示範在 `kw_tools.html` 勾選 **Regex 模式**，輸入一個 IP pattern，
對含有多個不同 IP 的伺服器清單執行各項操作。

## 操作步驟

1. 開啟 `kw_tools.html`
2. 勾選 **Regex 模式**
3. 在 Keywords 欄位填入：`\d+\.\d+\.\d+\.\d+`
4. 載入 `input.txt` 作為輸入
5. 切換不同 tab 執行操作

---

## 輸入（input.txt）

```
# Server inventory
server 127.0.0.1 role=web
server 127.0.0.2 role=web
server 10.0.0.1  role=db
server 10.0.0.2  role=db
server 192.168.1.100 role=cache
# Firewall rules
allow 127.0.0.1 -> 10.0.0.1 port=5432
allow 127.0.0.2 -> 10.0.0.2 port=5432
deny 0.0.0.0/0
```

---

## Search 結果（search_output.txt）

偵測到 **10 個 IP 出現**，涵蓋 **6 個不同 IP**：

```
L2: 8 [127.0.0.1]    server 127.0.0.1 role=web
L3: 8 [127.0.0.2]    server 127.0.0.2 role=web
L4: 8 [10.0.0.1]     server 10.0.0.1  role=db
L5: 8 [10.0.0.2]     server 10.0.0.2  role=db
L6: 8 [192.168.1.100] server 192.168.1.100 role=cache
L8: 7 [127.0.0.1]    allow 127.0.0.1 -> 10.0.0.1 port=5432
L8:20 [10.0.0.1]     allow 127.0.0.1 -> 10.0.0.1 port=5432
L9: 7 [127.0.0.2]    allow 127.0.0.2 -> 10.0.0.2 port=5432
L9:20 [10.0.0.2]     allow 127.0.0.2 -> 10.0.0.2 port=5432
L10: 6 [0.0.0.0]     deny 0.0.0.0/0
```

---

## Replace 結果（replace_output.txt + replace_mapping.json）

每個 **不同 IP** 取得獨立 token；**相同 IP** 共用同一個 token（如 `127.0.0.1` 在 L2 和 L8 均替換為同一個 token）。

**replace_output.txt：**
```
# Server inventory
server [[KW_...]] role=web      ← 127.0.0.1
server [[KW_...]] role=web      ← 127.0.0.2
server [[KW_...]]  role=db      ← 10.0.0.1
server [[KW_...]]  role=db      ← 10.0.0.2
server [[KW_...]] role=cache    ← 192.168.1.100
# Firewall rules
allow [[KW_...]] -> [[KW_...]] port=5432   ← 127.0.0.1 / 10.0.0.1（同上 token）
allow [[KW_...]] -> [[KW_...]] port=5432   ← 127.0.0.2 / 10.0.0.2（同上 token）
deny [[KW_...]]/0               ← 0.0.0.0
```

**replace_mapping.json（共 6 個 token）：**
```json
{
  "[[KW_...]]": "127.0.0.1",
  "[[KW_...]]": "127.0.0.2",
  "[[KW_...]]": "10.0.0.1",
  "[[KW_...]]": "10.0.0.2",
  "[[KW_...]]": "192.168.1.100",
  "[[KW_...]]": "0.0.0.0"
}
```

> 實際 token 值為隨機 hex（例如 `[[KW_3F9A1B2C]]`），每次執行不同。
> 完整內容見 `replace_output.txt` / `replace_mapping.json`。

---

## Cleanlog 結果（cleanlog_output.txt）

移除所有含 IP 的行（共 **8 行**），僅保留純註解行：

```
# Server inventory
# Firewall rules
```

---

## 自動化測試

上述行為均有對應測試案例：

```bash
node tests/test_kw_tools_html.js
# demo_regex_ip scenario
#   ✓  demo: search finds 10 IP occurrences across 8 lines
#   ✓  demo: search line numbers are correct
#   ✓  demo: replace produces 6 unique tokens for 6 distinct IPs
#   ✓  demo: replace reuses token for repeated IP (127.0.0.1 appears twice)
#   ✓  demo: replace output contains no raw IPs
#   ✓  demo: cleanlog removes 8 lines with IPs, keeps 2 comment lines
```
