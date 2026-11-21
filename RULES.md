# 📜 MERCHANT PREDICTOR — CẨM NANG QUY LUẬT GAME

> Tài liệu này giải thích cách hệ thống dự đoán vị trí Merchant. 
> Sử dụng ngôn ngữ thân thiện với người chơi game.

---

## PHẦN 1: CÁC KHÁI NIỆM CƠ BẢN

| Thuật ngữ | Giải thích cho người chơi |
|---|---|
| **1 Slot** | Merchant xuất hiện 4 lần/ngày (cách nhau 6 tiếng: 04:00, 10:00, 16:00, 22:00). **Mỗi lần chỉ ở lại 2 tiếng.** |
| **Chu kỳ gốc** | **119 slot** (tương đương khoảng 29 ngày 18 giờ). |
| **Mốc gốc (slot 0)** | 04:00 ngày 01/01/2025. (Có thể tùy chỉnh qua `base_time` trong `known_patterns.txt`) |

---

## PHẦN 2: QUY TẮC 3 MỐC THƯỜNG (10:00, 16:00, 22:00)

### 2.1. Quy tắc chính (Chu kỳ 119) & Rule 2 Vị trí đầu
👉 **Merch hiện tại giống hệt với Merch của 119 slot về trước.**
- **Rule 2 vị trí đầu (Smart Classify):** Để tránh lỗi đánh máy (typo) của người chơi làm nhiễu dữ liệu, hệ thống chỉ so sánh **2 vị trí đầu tiên**. Nếu 2 vị trí đầu trùng khớp, hệ thống coi đó là cùng một Pattern.
- Quy tắc này đúng trong khoảng ~95% các trường hợp.

### 2.2. Khi nào Merch bị "Lệch Nhịp" (Dị thường)?
- Khoảng 5% còn lại, Merch sẽ bị lệch so với chu kỳ 119. Gọi là **Dị thường** (Anomaly).
- Các lần lệch nhịp này tuân theo công thức: `Khoảng cách = k * 116 + p * 16` (với k, p là số nguyên).
- Các gap cơ bản: Lệch **16**, **116**, hoặc **132**.

### 2.3. Dãy Nhịp Điệu (14-Gap Pattern)
- Hệ thống đóng gói các nhịp điệu lệch nhịp phổ biến nhất thành một vòng lặp 14 bước:
  `[16, 116, 16, 116, 16, 116, 16, 116, 16, 116, 16, 132, 132, 132]`
- **Điểm bắt đầu:** Mốc 10:00 (bước 6), 16:00 (bước 12), 22:00 (bước 2).

### 2.4. Lấy lại Merch khi bị Lệch (Mốc Dự phòng - Phase A)
Khi hệ thống báo sắp có Dị thường, nó sẽ lấy Merch từ mốc dự phòng: `k * 119 + 12`.
- **10:00:** Lùi **488 slot** | **16:00:** Lùi **369 slot** | **22:00:** Lùi **250 slot**.

### 2.5. Nhận biết Rủi ro & Bắt "Bóng Ma" (Ghost Gap V3)
- **Báo động đỏ (116 hoặc 132 slot):** Hệ thống gạt bỏ 119, chuyển sang Phase A.
- **Báo động vàng (16 slot):** Hệ thống dựa vào dãy 14-gap để đoán.
- **Luật Bóng Ma (Ghost Gap V3):** Đôi khi Dev tạo ra một Gap 16 "giả" (như tại slot 682) để đánh lừa. Hệ thống sử dụng công thức toán học đồng dư: `(Target + 132) % 1072 == Mốc Extra Anomaly`. Nếu trùng khớp, đó là Bóng Ma, hệ thống sẽ **bỏ qua Risk và tin tưởng tuyệt đối vào 119**.

---

## PHẦN 3: QUY TẮC MỐC ĐẶC BIỆT 04:00 (NỬA ĐÊM)

Mốc 04:00 **TÁCH BIỆT HOÀN TOÀN** khỏi chu kỳ 119. Nó không dùng 119, không dùng Ghost Gap 1072. Nó chỉ dùng ma trận **Trạng thái (Phase)**: A1, A2, A3, A4, B3, C7.

### 3.1. Công thức sinh Khoảng cách lệch tại 04:00
- **Công thức:** `Khoảng cách = k * 119 + p * Jitter_04` với `Jitter_04 = [12, 6, -6, -12]`.

### 3.2. Nhịp điệu của các Nhánh (Branch Gaps)
- **Nhánh C1:** Lệch 16 slot. Nếu có 4 lần lệch 16 liên tiếp -> lần tiếp theo nhảy vọt thành [68, 84, 100].
- **Nhánh A3:** Lệch 16 -> A3; Lệch 100/84 -> A4; Lệch 4 -> C7.

### 3.3. Các quy tắc V12 (Dựa trên chuỗi Trạng thái)
- **V12.15 (Chuỗi A1):** Nếu trạng thái trước là B -> A -> A1 và lệch 4 slot -> Ưu tiên dự đoán A1 (lùi 131) hoặc A2 (lùi 250).

### 3.4. Hệ thống Phân tầng
| # | Nguồn | Ghi chú |
|---:|---|---|
| 1 | V12 (Chuỗi trạng thái) | Lõi chính (100% chính xác) |
| 2 | Markov B2 | Dựa trên 2 trạng thái trước đó |
| 3 | Markov B1 | Dựa trên nhánh A2 |
| 4 | Bảng TRANS | Lịch sử chuyển đổi trạng thái |
| 5 | Cụm 04:00 | Dựa trên công thức k, p ở mục 3.1 |

---

## PHẦN 4: QUY TẮC VẬN HÀNH CỦA BOT

1. **Bot Cào Dữ Liệu:** Chạy 4 lần/ngày. Quét kênh Discord 7 ngày gần nhất.
2. **Cơ chế An Toàn (Safety Check):**
   - File > 1MB -> Tự động tải bằng `download_url`.
   - Số dòng mới < 90% số dòng cũ -> Hủy lệnh (ABORT).
3. **Bảo mật:** Không nhúng Token vào URL, dùng `http.extraheader`.

---

## PHẦN 5: CẤU TRÚC MERCH (PATTERN)
- 6 cặp `stage-wave`. 6 nhóm stage: 1-4, 5-8, 9-12, 13-16, 17-20, 21-24.
- Vị trí thứ mấy thì luôn thuộc nhóm đó.


## 🛠️ Lịch Sử Cập Nhật & Quy Tắc Cốt Lõi (Cập nhật)

### 1. Quy tắc Timezone & Timestamp
- **Snowflake là Ground Truth:** `(ID >> 22) + 1420070400000` là nguồn thời gian chính xác nhất. Dùng để verify hoặc fallback.
- **Format bắt buộc:** Mọi timestamp phải là ISO 8601 (`%Y-%m-%d %H:%M:%S`). Cấm dùng `%m/%d/%Y` (gây lỗi đảo ngày/tháng). Múi giờ chuẩn là UTC+7 (VN).
- **Upload CSV:** Không tự động detect được timezone nếu CSV thiếu `Z` hoặc `+07:00`. Phải dùng thanh trượt UTC Offset của User để convert dữ liệu "Naive" về UTC+7.

### 2. Quy tắc Privacy & Hashing
- **HMAC-SHA256:** Username phải được hash bằng HMAC kết hợp key bí mật (chống reverse).
- **Key Management:** Key lưu ở `hash_key.txt`. File này bắt buộc phải commit lên Git để CI/CD đọc được.

### 3. Quy tắc UI Streamlit
- **Vị trí Slider:** Thanh trượt Timezone phải nằm trên cùng. Bắt buộc chèn **sau** khi biến `lang` và hàm dịch `T()` được khởi tạo (tránh `NameError`).
- **Cảnh báo Timezone:** Phải hiển thị ngay dưới `st.file_uploader`.

### 4. Quy tắc Code Patching
- **Cấm dùng Regex để patch file:** Tuyệt đối không dùng Regex tự động cắt/dán code. Phải sửa tay hoặc dùng logic line-by-line kiểm tra index cẩn thận để tránh `IndentationError`.

### 6. Data Processing & Predictor Logic
- **Trans History (Time Travel):** Cho phép user xem dự đoán ở các mốc thời gian trong quá khứ/tương lai. Slider nhận giá trị `offset_days` (-7 đến +30 ngày). Mỗi ngày tương ứng 4 slots (04:00, 10:00, 16:00, 22:00). Các slot bị thiếu dữ liệu (missing_04) sẽ được highlight trong popover.
- **Known Patterns & Mapping:** Dữ liệu đầu vào là các chuỗi kèo (vd: "3-15"). Sử dụng `item_utils.py` để dịch ID thành tên item. Cơ chế dự đoán phân tích tần suất xuất hiện của các cặp Item trong 30 slots gần nhất. **Lưu ý:** Tuyệt đối không sửa đổi cấu trúc file `known_patterns.txt` và `trans_history.txt` bằng tay, vì Predictor sẽ parse lỗi và crash app.