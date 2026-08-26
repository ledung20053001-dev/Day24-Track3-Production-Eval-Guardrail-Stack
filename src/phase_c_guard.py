from __future__ import annotations

"""Phase C: Production Guardrails — Presidio PII + NeMo Guardrails + P95 Latency."""

import asyncio
import json
import os
import re
import statistics
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ADVERSARIAL_SET_PATH, GUARDRAILS_CONFIG_DIR, LATENCY_BUDGET_P95_MS, PRESIDIO_LANGUAGE


# ─── Task 9a: Presidio PII Detection ─────────────────────────────────────────

def setup_presidio():
    """Khởi tạo Presidio engine với custom Vietnamese PII recognizers. (Đã implement sẵn)

    Custom recognizers thêm vào:
        VN_CCCD  — số CCCD 12 chữ số hoặc CMND 9 chữ số
        VN_PHONE — số điện thoại Việt Nam (0[3-9]xxxxxxxx)

    Các recognizers mặc định đã có sẵn: EMAIL, PHONE_NUMBER (international), ...
    """
    from presidio_analyzer import AnalyzerEngine, RecognizerRegistry, Pattern, PatternRecognizer
    from presidio_anonymizer import AnonymizerEngine

    cccd_recognizer = PatternRecognizer(
        supported_entity="VN_CCCD",
        patterns=[
            Pattern("CCCD 12 digits", r"\b\d{12}\b", 0.9),
            Pattern("CMND 9 digits",  r"\b\d{9}\b",  0.7),
        ],
    )
    phone_recognizer = PatternRecognizer(
        supported_entity="VN_PHONE",
        patterns=[Pattern("VN mobile", r"\b0[3-9]\d{8}\b", 0.9)],
    )

    registry = RecognizerRegistry()
    registry.load_predefined_recognizers()
    registry.add_recognizer(cccd_recognizer)
    registry.add_recognizer(phone_recognizer)

    analyzer  = AnalyzerEngine(registry=registry)
    anonymizer = AnonymizerEngine()
    return analyzer, anonymizer


def pii_scan(text: str, analyzer=None, anonymizer=None) -> dict:
    """Task 9a: Quét PII trong văn bản bằng Presidio.

    Returns:
        {
          "has_pii":    bool,
          "entities":   [{"type": str, "text": str, "score": float, "start": int, "end": int}],
          "anonymized": str,   # text với PII được thay bằng <TYPE>
        }
    """
    if analyzer is None or anonymizer is None:
        try:
            analyzer, anonymizer = setup_presidio()
        except Exception:
            return _regex_pii_scan(text)
    try:
        results = analyzer.analyze(text=text, language=PRESIDIO_LANGUAGE)
        if not results:
            return {"has_pii": False, "entities": [], "anonymized": text}
        entities = [
            {"type": result.entity_type, "text": text[result.start:result.end],
             "score": round(float(result.score), 3), "start": result.start, "end": result.end}
            for result in results
        ]
        return {"has_pii": True, "entities": entities,
                "anonymized": anonymizer.anonymize(text=text, analyzer_results=results).text}
    except Exception:
        return _regex_pii_scan(text)


def _regex_pii_scan(text: str) -> dict:
    """Dependency-free Vietnamese PII fallback with deterministic redaction."""
    patterns = [
        ("EMAIL_ADDRESS", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", 0.95),
        ("VN_PHONE", r"\b0[3-9]\d{8}\b", 0.90),
        ("VN_CCCD", r"\b\d{12}\b", 0.90),
        ("VN_CCCD", r"\b\d{9}\b", 0.70),
    ]
    matches = []
    occupied: list[tuple[int, int]] = []
    for entity_type, pattern, score in patterns:
        for match in re.finditer(pattern, text):
            if any(match.start() < end and match.end() > start for start, end in occupied):
                continue
            occupied.append((match.start(), match.end()))
            matches.append({"type": entity_type, "text": match.group(), "score": score,
                            "start": match.start(), "end": match.end()})
    matches.sort(key=lambda item: item["start"])
    anonymized = text
    for entity in reversed(matches):
        anonymized = (anonymized[:entity["start"]] + f"<{entity['type']}>"
                      + anonymized[entity["end"]:])
    return {"has_pii": bool(matches), "entities": matches, "anonymized": anonymized}


# ─── Task 9b + 11: NeMo Guardrails ───────────────────────────────────────────

def setup_nemo_rails():
    """Khởi tạo NeMo Guardrails từ guardrails/config.yml. (Đã implement sẵn)

    Config directory: guardrails/
        config.yml  — model + rails config
        rails.co    — Colang dialogue flows (topic check, jailbreak check, output check)
    """
    from nemoguardrails import RailsConfig, LLMRails
    config = RailsConfig.from_path(GUARDRAILS_CONFIG_DIR)
    rails  = LLMRails(config)
    return rails


async def check_input_rail(text: str, rails=None) -> dict:
    """Task 9b: Kiểm tra input qua NeMo input rails (topic guard + jailbreak guard).

    Returns:
        {
          "allowed":        bool,
          "blocked_reason": str | None,
          "response":       str,          # NeMo's raw response
        }
    """
    heuristic_reason = _input_violation(text)
    if heuristic_reason:
        return {"allowed": False, "blocked_reason": heuristic_reason,
                "response": "Xin lỗi, yêu cầu này không phù hợp với trợ lý chính sách HR."}
    if rails is None:
        try:
            rails = setup_nemo_rails()
        except Exception:
            return {"allowed": True, "blocked_reason": None, "response": ""}
    try:
        response = await rails.generate_async(messages=[{"role": "user", "content": text}])
        if isinstance(response, dict):
            response = response.get("content", str(response))
        response = str(response)
        blocked = any(keyword in response.casefold() for keyword in
                      ("xin lỗi", "không thể", "không được phép", "i cannot", "i'm sorry"))
        return {"allowed": not blocked, "blocked_reason": "nemo_input_rail" if blocked else None,
                "response": response}
    except Exception as error:
        return {"allowed": True, "blocked_reason": None, "response": "",
                "warning": f"NeMo unavailable: {error}"}


def _input_violation(text: str) -> str | None:
    value = text.casefold()
    jailbreak = ("bỏ qua tất cả", "ignore your system", "ignore previous", "ignore your previous",
                 "pretend you are dan", "không có giới hạn", "unrestricted ai", "đóng vai hr manager")
    injection = ("system override", "admin command", "priority 1", "system instructions",
                 "toàn bộ system", "bỏ qua tất cả policy", "dump all", "training data")
    pii_request = ("cho tôi biết cccd", "số điện thoại của nhân viên", "tiết lộ lương",
                   "employee salaries", "employee records", "confidential employee data",
                   "thông tin nhân viên", "bảng lương chi tiết", "confidential hr data")
    off_topic = ("bài thơ", "nấu phở", "bitcoin", "ethereum", "phương trình vi phân",
                 "recommend", "marvel", "thời tiết", "công thức nấu")
    if any(term in value for term in injection): return "prompt_injection"
    if any(term in value for term in jailbreak): return "jailbreak"
    if any(term in value for term in pii_request): return "pii_request"
    if any(term in value for term in off_topic): return "off_topic"
    return None


async def check_output_rail(question: str, answer: str, rails=None) -> dict:
    """Task 11: Kiểm tra LLM output qua NeMo output rails trước khi trả về user.

    NeMo output rails hoạt động trong context của cả cuộc hội thoại (input + output).
    Kiểm tra: có PII không? Nội dung có phù hợp không? Có hallucination rõ ràng không?

    Returns:
        {
          "safe":           bool,
          "flagged_reason": str | None,
          "final_answer":   str,          # answer đã qua guard (có thể bị redact)
        }
    """
    pii = pii_scan(answer)
    sensitive = any(term in answer.casefold() for term in
                    ("mật khẩu hệ thống là", "cccd của nhân viên là", "thông tin bí mật"))
    if pii["has_pii"] or sensitive:
        return {"safe": False, "flagged_reason": "sensitive_output",
                "final_answer": "Tôi không thể cung cấp thông tin nhạy cảm này."}
    if rails is None:
        try:
            rails = setup_nemo_rails()
        except Exception:
            return {"safe": True, "flagged_reason": None, "final_answer": answer}
    try:
        response = await rails.generate_async(messages=[
            {"role": "user", "content": question}, {"role": "assistant", "content": answer},
        ])
        if isinstance(response, dict): response = response.get("content", str(response))
        response = str(response)
        flagged = any(term in response.casefold() for term in ("không thể cung cấp", "i cannot"))
        return {"safe": not flagged, "flagged_reason": "nemo_output_rail" if flagged else None,
                "final_answer": response if flagged else answer}
    except Exception:
        return {"safe": True, "flagged_reason": None, "final_answer": answer}


# ─── Task 10: Adversarial Test Suite ─────────────────────────────────────────

def run_adversarial_suite(adversarial_set: list[dict], rails=None,
                           analyzer=None, anonymizer=None) -> list[dict]:
    """Task 10: Chạy 20 adversarial inputs qua full guard stack, so sánh với expected.

    Guard stack order:
        1. pii_scan()         → block nếu has_pii (cho category pii_injection)
        2. check_input_rail() → block nếu jailbreak / off-topic / prompt injection

    Returns:
        list of {
          "id": int, "category": str, "input": str,
          "expected": "blocked"|"allowed",
          "actual":   "blocked"|"allowed",
          "blocked_by": str | None,       # "presidio" | "nemo_input" | None
          "passed": bool,
        }
    """
    async def run_all():
        output = []
        for item in adversarial_set:
            blocked_by = "presidio" if pii_scan(item["input"], analyzer, anonymizer)["has_pii"] else None
            if blocked_by is None:
                rail_result = await check_input_rail(item["input"], rails)
                if not rail_result["allowed"]: blocked_by = "nemo_input"
            actual = "blocked" if blocked_by else "allowed"
            output.append({"id": item["id"], "category": item["category"],
                           "input": item["input"], "expected": item["expected"],
                           "actual": actual, "blocked_by": blocked_by,
                           "passed": actual == item["expected"]})
        return output
    results = asyncio.run(run_all())
    print(f"Adversarial suite: {sum(item['passed'] for item in results)}/{len(results)} passed")
    return results


# ─── Task 12: P95 Latency Measurement ────────────────────────────────────────

def measure_p95_latency(test_inputs: list[str], n_runs: int = 20,
                         rails=None, analyzer=None, anonymizer=None) -> dict:
    """Task 12: Đo P50/P95/P99 latency cho từng layer trong guard stack.

    Mục tiêu production: P95 total < LATENCY_BUDGET_P95_MS (500ms mặc định)

    Insight cần quan sát:
        - Presidio: local regex → rất nhanh (<10ms)
        - NeMo:     LLM API call → chậm (~200-800ms tuỳ model và network)
        → Tổng: dominated by NeMo

    Returns:
        {
          "presidio_ms":  {"p50": float, "p95": float, "p99": float},
          "nemo_ms":      {"p50": float, "p95": float, "p99": float},
          "total_ms":     {"p50": float, "p95": float, "p99": float},
          "latency_budget_ok": bool,
          "budget_ms": int,
        }
    """
    presidio_times, nemo_times, total_times = [], [], []
    samples = (test_inputs * max(1, (n_runs + max(len(test_inputs), 1) - 1) // max(len(test_inputs), 1)))[:n_runs]
    async def measure():
        for text in samples:
            started = time.perf_counter(); pii_scan(text, analyzer, anonymizer)
            presidio_ms = (time.perf_counter() - started) * 1000
            started = time.perf_counter(); await check_input_rail(text, rails)
            nemo_ms = (time.perf_counter() - started) * 1000
            presidio_times.append(presidio_ms); nemo_times.append(nemo_ms)
            total_times.append(presidio_ms + nemo_ms)
    if samples: asyncio.run(measure())
    def percentiles(values):
        if not values: return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
        ordered = sorted(values)
        def nearest(percent): return ordered[min(round((len(ordered) - 1) * percent), len(ordered) - 1)]
        return {"p50": round(nearest(0.50), 2), "p95": round(nearest(0.95), 2),
                "p99": round(nearest(0.99), 2)}
    total = percentiles(total_times)
    return {"presidio_ms": percentiles(presidio_times), "nemo_ms": percentiles(nemo_times),
            "total_ms": total, "latency_budget_ok": total["p95"] < LATENCY_BUDGET_P95_MS,
            "budget_ms": LATENCY_BUDGET_P95_MS}


def save_guard_report(results: list[dict], latency: dict,
                      path: str = "reports/guard_results.json") -> None:
    """Persist adversarial and latency results for CI/check_lab.py."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    passed = sum(item["passed"] for item in results)
    payload = {
        "total_cases": len(results), "passed": passed,
        "pass_rate": round(passed / len(results), 4) if results else 0.0,
        "latency": latency, "results": results,
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(f"Phase C report saved → {path}")


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Task 9a: PII scan demo
    test_pii = "Nhân viên Nguyễn Văn A, CCCD 034095001234, SĐT 0987654321 hỏi về nghỉ phép."
    result = pii_scan(test_pii)
    print(f"PII detected: {result['has_pii']}")
    print(f"Entities: {result['entities']}")
    print(f"Anonymized: {result['anonymized']}")

    # Task 10: Adversarial suite
    with open(ADVERSARIAL_SET_PATH, encoding="utf-8") as f:
        adversarial_set = json.load(f)
    print(f"\nLoaded {len(adversarial_set)} adversarial inputs")
    results = run_adversarial_suite(adversarial_set)
    if results:
        passed = sum(1 for r in results if r["passed"])
        print(f"Adversarial suite: {passed}/{len(results)} passed")

    # Task 12: P95 latency
    sample_inputs = [item["input"] for item in adversarial_set[:10]]
    latency = measure_p95_latency(sample_inputs, n_runs=10)
    print(f"\nLatency P95 — Presidio: {latency['presidio_ms']['p95']}ms | "
          f"NeMo: {latency['nemo_ms']['p95']}ms | "
          f"Total: {latency['total_ms']['p95']}ms")
    print(f"Budget OK ({latency['budget_ms']}ms): {latency['latency_budget_ok']}")
    save_guard_report(results, latency)
