# CI/CD Blueprint: RAG Eval + Guardrail Stack

## Guard Stack Pipeline

| Layer | Tool | Latency P95 | Failure Action |
|---|---|---:|---|
| PII Detection | Presidio + regex fallback | 1.01 ms | Reject + log |
| Topic/Jailbreak | NeMo Input + local fallback | 0.44 ms | 503 + reason |
| RAG Pipeline | Day 18 | <2000 ms budget | Fallback |
| Output Check | NeMo Output + PII scan | <300 ms budget | Block + log |

> Latency trên được đo với `MOCK_MODE=true` trên 20 adversarial inputs. NeMo không gọi
> LLM qua mạng trong phép đo này, vì vậy số liệu chỉ phản ánh local fallback và không
> đại diện cho latency production của Gemini/OpenAI.

## CI Gates (phải pass trước khi merge to main)

- [x] Offline proxy faithfulness ≥ 0.75 (1.0000 trên 50q; chưa phải model-backed RAGAS)
- [x] Adversarial suite pass rate ≥ 90% (20/20)
- [x] P95 total guard latency < 500 ms (1.45 ms trong mock/local mode)

Offline gate đã pass, nhưng production gate vẫn cần model-backed RAGAS trước khi merge.

## Monitoring

- P95 latency thực tế: **1.45 ms** (mock/local fallback)
- Adversarial pass rate: **20/20**
- Worst offline metric: **answer_relevancy**
- Dominant failure distribution: **adversarial theo average score** (factual theo raw worst-metric count)

## Percentile Measurements

| Layer | P50 | P95 | P99 | Budget status |
|---|---:|---:|---:|---|
| Presidio PII | 0.31 ms | 1.01 ms | 1.01 ms | Pass |
| NeMo Input/local fallback | 0.01 ms | 0.44 ms | 0.44 ms | Pass |
| Total Guard | 0.31 ms | 1.45 ms | 1.45 ms | Pass (<500 ms) |

## Validation Summary

- [x] `pii_scan()` phát hiện `VN_CCCD`, `VN_PHONE` và email; dữ liệu được anonymize.
- [x] Adversarial suite đạt 20/20, cao hơn yêu cầu tối thiểu 15/20.
- [x] `measure_p95_latency()` trả đủ `presidio_ms`, `nemo_ms`, `total_ms`,
  `latency_budget_ok` và `budget_ms`, gồm P50/P95/P99.
- [x] Blueprint đã điền các kết quả hiện có và ghi rõ giới hạn của phép đo mock.

## Production Follow-up

Trước khi triển khai, chạy lại RAGAS trên 50 câu bằng Gemini/OpenAI với quota phù hợp
và đo NeMo qua mạng. CI chỉ được phép pass khi faithfulness thật đạt `0.75`, adversarial
suite vẫn đạt ít nhất `18/20`, và P95 total guard thật nhỏ hơn `500 ms`.
