# LLM Judge Bias Report — Phase B

**Sinh viên:** Lê Công Dũng

**Ngày:** 26/08/2026
**Judge:** Offline deterministic proxy (không dùng API key)

## 1. Pairwise Judge Results

Answer A là `model_answer`; Answer B là ground truth tương ứng.

| # | Question tóm tắt | Winner | Nhận xét |
|---:|---|---|---|
| 1 | Nghỉ khi kết hôn | tie | Hai câu trả lời có độ liên quan gần nhau |
| 2 | Phê duyệt mua thiết bị 55 triệu | tie | Fallback không phát hiện sai ngưỡng phê duyệt |
| 3 | Thưởng Tết tối thiểu | B | Ground truth được chấm cao hơn |
| 4 | Senior 9 năm: phép và lương | tie | Hai câu trả lời gần tương đương lexical |
| 5 | Hoàn trả khóa học 25 triệu | B | Ground truth được chấm cao hơn |
| 6 | Tạm ứng 8 triệu quá hạn | B | Ground truth đầy đủ hơn |
| 7 | Manager 12 năm | B | Ground truth đầy đủ hơn |
| 8 | Số ngày phép năm | A | Fallback chọn answer cũ, cho thấy hạn chế version reasoning |
| 9 | Thử việc có phép năm không | B | Ground truth được chấm cao hơn |
| 10 | VPN cá nhân khi WFH | B | Ground truth được chấm cao hơn |

## 2. Swap-and-Average Results

| # | Pass 1 | Pass 2 | Final | Position Consistent? |
|---:|---|---|---|---|
| 1 | tie | tie | tie | Yes |
| 2 | tie | tie | tie | Yes |
| 3 | B | B | B | Yes |
| 4 | tie | tie | tie | Yes |
| 5 | B | B | B | Yes |
| 6 | B | B | B | Yes |
| 7 | B | B | B | Yes |
| 8 | A | A | A | Yes |
| 9 | B | B | B | Yes |
| 10 | B | B | B | Yes |

**Position bias rate:** 0/10 = **0.0%**. Đây là kết quả kỳ vọng của fallback đối xứng,
không chứng minh Gemini/OpenAI không có position bias.

## 3. Cohen's κ Analysis

Judge label được tính riêng bằng numeric consistency và token F1 giữa model answer với
ground truth; ngưỡng F1 là `0.45`.

| Question ID | Human | Judge | Agree? |
|---:|---:|---:|---|
| 1 | 1 | 1 | Yes |
| 5 | 0 | 1 | No |
| 12 | 1 | 0 | No |
| 21 | 1 | 1 | Yes |
| 23 | 1 | 0 | No |
| 29 | 0 | 0 | Yes |
| 33 | 1 | 1 | Yes |
| 41 | 0 | 0 | Yes |
| 46 | 1 | 1 | Yes |
| 50 | 0 | 0 | Yes |

**Cohen's κ:** `0.4000`

**Interpretation:** moderate agreement; proxy tốt hơn baseline ngẫu nhiên nhưng chưa đạt
ngưỡng `0.6` để làm production judge.

## 4. Verbosity Bias

- Winner rõ ràng: 7 cases
- A thắng và A dài hơn B: 0 cases
- B thắng và B dài hơn A: 6 cases
- **Verbosity bias rate:** 6/7 = **85.7%**

Tỷ lệ cao cho thấy scoring fallback ưu tiên câu trả lời dài/đầy đủ hơn. Đây là bias
đáng lo vì câu dài không đồng nghĩa với chính xác, đặc biệt ở câu hỏi xung đột phiên bản.

## 5. Nhận xét chung

Kappa đạt `0.4` nhưng chưa đạt ngưỡng `0.6`, do đó judge offline chưa đủ tin cậy để làm
CI quality gate. Position bias bằng zero chủ yếu do thuật toán fallback tất định và đối xứng;
swap-and-average vẫn cần thiết khi chuyển sang LLM thật. Trước production, phải chạy
lại 10 mẫu bằng Gemini/OpenAI ở temperature 0, giữ structured JSON, so sánh với human
labels và chỉ chấp nhận judge khi κ vượt `0.6`.
