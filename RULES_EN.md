# 📜 MERCHANT PREDICTOR — MASTER GAME RULES

> This document explains how the system predicts Merchant locations. 
> Using player-friendly language. (Times are based on VN Time / UTC+7).

---

## PART 1: BASIC CONCEPTS

| Term | Explanation for Players |
|---|---|
| **Game Reset** | The game resets daily at **07:00 AM (VN Time)**. |
| **1 Slot** | Merchant appears 4 times/day. Each appearance lasts only 2 hours. |
| **Merch Cycles** | **1st Merch** (10:00), **2nd Merch** (16:00), **3rd Merch** (22:00), and **Last Merch** (04:00). |
| **Base Cycle** | **119 slots** (approx. 29 days 18 hours). |

---

## PART 2: RULES FOR 3 REGULAR MERCHS (1st, 2nd, 3rd)

### 2.1. Main Rule & Smart Classify (First 2 Pairs)
👉 **Current Merch is identical to the Merch from 119 slots ago.**
- **Smart Classify:** To filter out player typos, the system only compares the **first 2 position pairs**. If they match, the patterns are considered identical. (Only applies to regular Merch).

### 2.2. When does Merch "Shift" (Anomaly)?
- Basic shift gaps are: **16**, **116**, or **132**.

### 2.3. Rhythm Sequence (14-Gap Pattern)
- The system packages these rhythms into a 14-step loop:
  `[16, 116, 16, 116, 16, 116, 16, 116, 16, 116, 16, 132, 132, 132]`

### 2.4. Fallback Merch (Phase A)
- **1st Merch:** -**488 slots** | **2nd Merch:** -**369 slots** | **3rd Merch:** -**250 slots**.

### 2.5. Risk Detection & Ghost Gap V3
- **Red Alert (116 or 132 gaps):** Drops Cycle 119 and uses **Phase A**.
- **Yellow Alert (16 gap):** Checks the 14-gap sequence to decide.
- **Ghost Gap V3:** Sometimes the Dev creates a "fake" 16 gap (like at slot 682). The system uses a mathematical modulo formula: `(Target + 132) % 1072 == Extra_Pos`. If true, it ignores the risk and trusts 119 completely.

---

## PART 3: SPECIAL LAST MERCH (04:00 BEFORE RESET)

The Last Merch is **COMPLETELY SEPARATED** from Cycle 119. It does NOT use 119 or Ghost Gap. It uses a **Phase Matrix**: A1, A2, A3, A4, B3, C7.

### 3.1. Gap Formula for Last Merch
- **Formula:** `Gap = k * 119 + p * Jitter` where `Jitter = [12, 6, -6, -12]`.

### 3.2. Branch Rhythms
- **Branch C1:** Usually 16 slots. If 4 consecutive 16-gaps -> next jumps to [68, 84, 100].
- **Branch A3:** 16 -> A3; 100/84 -> A4; 4 -> C7.

### 3.3. V12 Rules (State Chains)
- **V12.15 (A1 Chain):** If previous states are B -> A -> A1 and gap = 4 -> Prioritize A1 (-131) or A2 (-250).

### 3.4. Tier System
| # | Source | Note |
|---:|---|---|
| 1 | V12 (State Chain) | Core engine (100% accurate) |
| 2 | Markov B2 | Based on previous 2 states |
| 3 | Markov B1 | Based on A2 branch |
| 4 | TRANS Table | Historical state transitions |
| 5 | Cluster | Based on k, p formula |

---

## PART 4: BOT OPERATIONS
- Bot runs 4 times/day. Auto-handles >1MB files and prevents data loss.
- 6 `stage-wave` pairs. Positions strictly map to stage groups.


## 🛠️ Update History & Core Rules (Updated)

### 1. Timezone & Timestamp Rules
- **Snowflake Ground Truth:** `(ID >> 22) + 1420070400000` is the most accurate time source. Use it to verify or fallback.
- **Mandatory Format:** All timestamps must be ISO 8601 (`%Y-%m-%d %H:%M:%S`). NEVER use `%m/%d/%Y` (causes day/month swap). Standard timezone is UTC+7 (VN).
- **Upload CSV:** Cannot auto-detect timezone if CSV lacks `Z` or `+07:00`. Must use User's UTC Offset slider to convert "Naive" data to UTC+7.

### 2. Privacy & Hashing Rules
- **HMAC-SHA256:** Usernames must be hashed using HMAC with a secret key (prevent reverse).
- **Key Management:** Key stored in `hash_key.txt`. This file MUST be committed to Git for CI/CD.

### 3. Streamlit UI Rules
- **Slider Position:** Timezone slider must be at the top. MUST be inserted **after** `lang` variable and `T()` translation function initialization (avoid `NameError`).
- **Timezone Warning:** Must be displayed directly below `st.file_uploader`.

### 4. Code Patching Rules
- **NEVER use Regex to patch files:** Absolutely do not use Regex to automatically cut/paste code. Use manual edit or strict line-by-line index logic to avoid `IndentationError`.

### 6. Data Processing & Predictor Logic
- **Trans History (Time Travel):** Allows users to view predictions at specific past/future timestamps. The slider accepts `offset_days` (-7 to +30 days). Each day corresponds to 4 slots (04:00, 10:00, 16:00, 22:00). Missing data slots (`missing_04`) will be highlighted in a popover.
- **Known Patterns & Mapping:** Input data consists of match strings (e.g., "3-15"). Uses `item_utils.py` to translate IDs to item names. The prediction mechanism analyzes the frequency of item pairs within the last 30 slots. **Note:** Absolutely do not manually modify the structure of `known_patterns.txt` and `trans_history.txt`, as the Predictor will fail to parse them and crash the app.

---

## Reference Anchor, Predictor Details & Web App Link

- **Web App:** [https://merchant-locs-patch1.streamlit.app](https://merchant-locs-patch1.streamlit.app)
- **Base Anchor (`BASE`):** `2025-01-01 04:00:00` (VN time, `UTC+7`), with 6-hour slots (`04:00`, `10:00`, `16:00`, `22:00` VN time).
- **04:00 Prediction Branch (`_predict_04am_ext`):** Handles `04:00` slots (`slot % 4 == 0`) using phase chains (`A1–A4, B3, C7`), dedicated gap offsets `GAPS_04` (`k*119 + p*j`), second-order Markov transitions (`MARKOV_B2` / `MARKOV_B2_2T`), `TRANS`, and recency matching.
- **Standard 10:00 / 16:00 / 22:00 Branch (`_predict_std_ext`):** Defaults to the `119` cycle (`CYCLE = 119`) and `1072` macro cycle (`MACRO_CYCLE = 1072`); applies `STD_ANOMALY_OFFSETS` on anomaly risk/slots and checks auxiliary positions `157`, `814`, `399` (including `ghost gap` checks along the `1072` cycle).
- **Lookback Cutoff Guard (`cutoff`):** Filters anomaly/gap history strictly prior to `cutoff_slot` / `target_slot` to prevent future data leakage.
- **Item Source Tracing & Time Decay (`_find_item_source`, `half_life`):** Resolves item origins via `_find_item_source` (direct/candidate source slot first, then prior matching-pattern slot) and weights aggregated items with slot-distance decay (`half_life = 200.0`).
