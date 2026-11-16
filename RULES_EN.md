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
