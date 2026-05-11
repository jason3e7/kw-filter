# Demo：Regex 模式 — `last` 登入記錄去識別化

示範在 `kw_tools.html` 勾選 **Regex 模式**，對 `last` 指令輸出
自動偵測並替換所有遠端登入 IP。

## 操作步驟

1. 開啟 `kw_tools.html`
2. 勾選 **Regex 模式**
3. 在 Keywords 欄位填入：`\d+\.\d+\.\d+\.\d+`
4. 載入 `input.txt` 作為輸入
5. 切換不同 tab 執行操作

---

## 輸入（input.txt）

```
alice    pts/0        203.0.113.15     Sun May 11 10:23   still logged in
bob      pts/1        198.51.100.42    Sun May 11 09:15 - 10:01  (00:46)
alice    pts/0        203.0.113.15     Sat May 10 22:11 - 23:05  (00:54)
charlie  pts/2        192.0.2.88       Sat May 10 20:33 - 21:10  (00:37)
root     tty1                          Sat May 10 18:00   still logged in
bob      pts/3        198.51.100.42    Sat May 10 15:22 - 17:48  (02:26)
mallory  pts/4        45.33.32.156     Sat May 10 14:05 - 14:06  (00:01)
alice    pts/1        203.0.113.15     Fri May  9 11:30 - 13:20  (01:50)
charlie  pts/0        192.0.2.88       Fri May  9 09:00 - 10:15  (01:15)
reboot   system boot  5.15.0-71-generic Fri May  9 08:55

wtmp begins Fri May  9 08:55:00 2026
```

---

## Search 結果（search_output.txt）

偵測到 **8 個 IP 出現**，涵蓋 **4 個不同 IP**。
`root`（本機登入）與 `reboot`（核心版本 `5.15.0-71-generic`）均不觸發：

```
L1:23 [203.0.113.15]   alice    pts/0  ...  still logged in
L2:23 [198.51.100.42]  bob      pts/1  ...
L3:23 [203.0.113.15]   alice    pts/0  ...
L4:23 [192.0.2.88]     charlie  pts/2  ...
L6:23 [198.51.100.42]  bob      pts/3  ...
L7:23 [45.33.32.156]   mallory  pts/4  ...
L8:23 [203.0.113.15]   alice    pts/1  ...
L9:23 [192.0.2.88]     charlie  pts/0  ...
```

---

## Replace 結果（replace_output.txt + replace_mapping.json）

**4 個不同 IP → 4 個 token**。
alice 登入 3 次，3 行均共用同一個 token（`203.0.113.15`）：

```
alice    pts/0        [[KW_...]]    Sun May 11 10:23   still logged in   ← token A
bob      pts/1        [[KW_...]]    Sun May 11 09:15 - 10:01  (00:46)   ← token B
alice    pts/0        [[KW_...]]    Sat May 10 22:11 - 23:05  (00:54)   ← token A（同上）
charlie  pts/2        [[KW_...]]    Sat May 10 20:33 - 21:10  (00:37)   ← token C
root     tty1                       Sat May 10 18:00   still logged in  ← 不變
bob      pts/3        [[KW_...]]    Sat May 10 15:22 - 17:48  (02:26)   ← token B（同上）
mallory  pts/4        [[KW_...]]    Sat May 10 14:05 - 14:06  (00:01)   ← token D
alice    pts/1        [[KW_...]]    Fri May  9 11:30 - 13:20  (01:50)   ← token A（同上）
charlie  pts/0        [[KW_...]]    Fri May  9 09:00 - 10:15  (01:15)   ← token C（同上）
reboot   system boot  5.15.0-71-generic Fri May  9 08:55                ← 不變
```

**replace_mapping.json（共 4 個 token）：**
```json
{
  "[[KW_...]]": "203.0.113.15",
  "[[KW_...]]": "198.51.100.42",
  "[[KW_...]]": "192.0.2.88",
  "[[KW_...]]": "45.33.32.156"
}
```

> 完整 token 值見 `replace_output.txt` / `replace_mapping.json`。

---

## Cleanlog 結果（cleanlog_output.txt）

移除所有含遠端 IP 的行（**8 行**），保留本機登入、重啟記錄與 wtmp 標頭：

```
root     tty1                          Sat May 10 18:00   still logged in
reboot   system boot  5.15.0-71-generic Fri May  9 08:55

wtmp begins Fri May  9 08:55:00 2026
```

---

## 自動化測試

```bash
node tests/test_kw_tools_html.js
# demo_last scenario
#   ✓  last: search finds 8 IP occurrences
#   ✓  last: search finds 4 unique IPs
#   ✓  last: kernel version 5.15.0-71-generic is not matched as IP
#   ✓  last: replace produces 4 tokens for 4 distinct IPs
#   ✓  last: alice IP (203.0.113.15) reused across 3 sessions
#   ✓  last: replace keeps root / reboot / wtmp lines untouched
#   ✓  last: cleanlog removes 8 remote-login lines, keeps 5 local lines
```
