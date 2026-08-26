# Failure Cluster Analysis — Phase A

**Sinh viên:** Lê Công Dũng

**Ngày:** 26/08/2026

**Chế độ đánh giá:** Offline lexical proxy — không dùng API key

## 1. Aggregate Scores theo Distribution

| Metric | factual | multi_hop | adversarial |
|---|---:|---:|---:|
| faithfulness | 1.0000 | 1.0000 | 1.0000 |
| answer_relevancy | 0.6756 | 0.4726 | 0.3662 |
| context_precision | 1.0000 | 1.0000 | 1.0000 |
| context_recall | 0.9150 | 0.6809 | 0.5219 |
| **avg_score** | **0.8976** | **0.7884** | **0.7220** |

Đây là proxy lexical tất định: faithfulness đo tỷ lệ token câu trả lời được hỗ trợ bởi
context; relevancy dùng token F1 với câu hỏi và ground truth; precision đo tỷ lệ chunks
có liên quan; recall đo độ phủ ground-truth tokens trong context. Các giá trị này hữu ích
để so sánh tương đối offline nhưng không tương đương model-backed RAGAS.

## 2. Bottom 10 Questions

| Rank | Dist. | ID | Question | avg | worst metric |
|---:|---|---:|---|---:|---|
| 1 | multi_hop | 39 | So sánh policy mật khẩu v1.0 và v2.0 | 0.6201 | answer_relevancy |
| 2 | adversarial | 41 | Nhân viên được nghỉ bao nhiêu ngày phép năm? | 0.6590 | answer_relevancy |
| 3 | adversarial | 43 | Mật khẩu phải có tối thiểu bao nhiêu ký tự? | 0.6603 | context_recall |
| 4 | adversarial | 48 | Thử việc có được hưởng bảo hiểm PVI không? | 0.6714 | answer_relevancy |
| 5 | multi_hop | 33 | Manager 12 năm: phụ cấp và phép năm | 0.6737 | answer_relevancy |
| 6 | adversarial | 42 | Bao nhiêu năm thì được cộng ngày phép? | 0.6867 | answer_relevancy |
| 7 | adversarial | 50 | Có thể dùng VPN cá nhân khi WFH không? | 0.6899 | answer_relevancy |
| 8 | multi_hop | 21 | Senior 9 năm: phép năm và khoảng lương | 0.6920 | answer_relevancy |
| 9 | adversarial | 44 | Bao lâu phải đổi mật khẩu? | 0.7037 | answer_relevancy |
| 10 | adversarial | 49 | So sánh phép năm v2023 và bản hiện hành | 0.7133 | answer_relevancy |

## 3. Failure Cluster Matrix

| worst_metric | factual | multi_hop | adversarial | Total |
|---|---:|---:|---:|---:|
| faithfulness | 0 | 0 | 0 | 0 |
| answer_relevancy | 20 | 19 | 8 | 47 |
| context_precision | 0 | 0 | 0 | 0 |
| context_recall | 0 | 1 | 2 | 3 |

## 4. Dominant Failure Analysis

**Dominant distribution:** factual theo raw count (20), đồng hạng multi-hop; kết luận
chất lượng phù hợp hơn là adversarial vì có average thấp nhất (`0.7220`).

**Dominant metric:** answer_relevancy (`47/50` câu có đây là metric thấp nhất).

Factual có raw count cao vì có 20 mẫu và relevancy thường là metric nhỏ nhất ngay cả
khi tổng điểm cao. Xét mức điểm thay vì count, adversarial mới là cụm khó nhất, tiếp đến
multi-hop. Các câu version conflict và negation có lexical mismatch lớn giữa câu hỏi,
context và câu trả lời, đồng thời retrieval phải phân biệt tài liệu cũ/hiện hành.

## 5. Suggested Fixes

| Metric yếu | Root cause | Suggested fix |
|---|---|---|
| answer_relevancy | Context/answer dài, chưa trả lời trực tiếp | Prompt trả lời ngắn trước, giải thích sau; query-aware generation |
| context_recall | Thiếu thông tin từ nhiều tài liệu | Query decomposition, tăng candidate top-k, parent retrieval |
| context_precision | Version cũ và mới cùng được retrieve | Metadata `effective_date/version`, filter bản hiện hành trước rerank |
| faithfulness | Nguy cơ suy diễn ngoài context | Temperature thấp, citation và kiểm tra entailment đầu ra |

## 6. Nhận xét về Adversarial Distribution

Adversarial có average `0.7220`, thấp hơn multi-hop `0.7884` và factual `0.8976`, đúng
kỳ vọng stress-test. Bảy trong bottom-10 là adversarial, tập trung vào phép năm, mật khẩu,
bảo hiểm thử việc và VPN cá nhân. Điều này cho thấy version conflict/negation là điểm yếu
rõ nhất; nên bổ sung metadata phiên bản và rule ưu tiên policy đang có hiệu lực.
