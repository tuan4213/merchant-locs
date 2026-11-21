# merchant-locs
just a tool for calculating where the merchant is ingame



## 📅 Update History (Changelog)

| Commit | Date & Time | Description |
| :--- | :--- | :--- |
| `61c01c6` | 2026-11-21 07:30:24 | Fix UI: Move slider after T() initialization, re-apply predictor patch |
| `6e45141` | 2026-11-21 07:27:52 | UI: Move UTC slider to top, add timezone warning, auto-convert logic |
| `3387f03` | 2026-11-21 06:51:13 | Patch L55 scraper: time_str dùng ISO thay MM/DD |
| `38c9b6f` | 2026-11-21 06:49:38 | Fix bot timezone output: ISO format + normalize 164 record mới |
| `bced113` | 2026-11-21 06:44:55 | 🤖 Auto-add merchant posts (2026-11-21) |
| `6e5c57b` | 2026-11-21 06:21:32 | Fix Timestamp: regenerate từ snowflake ID (ground truth) |
| `14af9cb` | 2026-11-21 06:01:04 | Re-hash data.csv SHA256→HMAC(4213) + commit hash_key.txt |
| `f0457a3` | 2026-11-21 05:52:23 | Bot đọc key từ hash_key.txt (commit luôn file) |
| `8c50b5e` | 2026-11-21 05:50:50 | Bot đọc key từ hash_key.txt (không hardcode) |
| `5534b99` | 2026-11-21 05:33:32 | Fix timestamp: ISO 8601 cho scraper + normalize data.csv |
| `3fcdafd` | 2026-11-21 05:13:46 | Re-hash data.csv sau khi merge remote từ bot |
| `f9b42d2` | 2026-11-21 05:13:45 | Merge remote data.csv từ bot |
| `c41f2cd` | 2026-11-21 05:13:45 | temp: remote data.csv |
| `c947be5` | 2026-11-21 05:13:04 | Privacy: hash username + bỏ Display Name/Server Nickname |
| `d9bca3b` | 2026-11-21 04:51:21 | Add GitHub workflows + scraper 30 ngày |
| `06c1238` | 2026-11-21 04:12:01 | FIX CRITICAL: 04:00 dùng _predict_04am_ext TRƯỚC, virtual fallback SAU |
| `eef7a14` | 2026-11-21 04:05:36 | Verify pass: chain + 2-tier sibling + 04:00 virtual - items=4052, meta=4375 - 3 slot 04:00 tương lai fill đủ + chain |
| `dd1016d` | 2026-11-21 03:31:33 | Fix items: fill position thiếu từ sibling gần nhất (cùng pattern, walk xuống) |
| `01f8f81` | 2026-11-21 02:42:43 | Fix: extract_items NGOÀI if pattern + slot_to_meta không bị nuốt vào except |
| `da7f6a8` | 2026-11-21 02:31:55 | Fix: extract_items không yêu cầu >=6 items (build slot_to_items đầy đủ) |
| `d90f901` | 2026-11-21 02:31:04 | Fix: build slot_to_items trong run_pipeline (restore items display) |
| `08ae9da` | 2026-11-19 23:36:31 | Fix: _slot_candidates + _slot_actual_candidates lookup items từ slot_to_items |
| `9a06adc` | 2026-11-19 23:34:39 | Fix: extract_items regex (yêu cầu có chữ cái, tránh garbage từ pattern-only) |
| `4480d49` | 2026-11-19 23:32:54 | Fix: xoá duplicate run_pipeline + build slot_to_items + extract_items skip pattern-only |
| `60cdd93` | 2026-11-20 06:04:45 | Pattern: ưu tiên tin pattern (người đăng cả pattern+items trước), tin items chỉ là dự phòng |
| `7878310` | 2026-11-20 06:04:44 | Pattern: ưu tiên tin pattern (người đăng cả pattern+items trước), tin items chỉ là dự phòng |
| `19e7094` | 2026-11-18 22:20:40 | Fix: _get_anomaly_risk predicted None → False (fix slot 495) |
| `8abce4f` | 2026-11-18 22:04:52 | Patch v2: Lấp tạm 04:00 thiếu (is_virtual flag), KHÔNG dùng 119 cho logic dự đoán |
| `6a0a772` | 2026-11-18 21:41:23 | Docs: mark predictor_2.py as experimental (logic-only, no CSV) |
| `01a11bc` | 2026-11-18 21:41:21 | Arch: classify dùng full-string (verify: 17 fails vs 17 current) |
