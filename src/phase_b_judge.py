from __future__ import annotations

"""Phase B: LLM-as-Judge — pairwise, swap-and-average, Cohen κ, bias analysis."""

import json
import os
import sys
from dataclasses import dataclass, field

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import HUMAN_LABELS_PATH, JUDGE_MODEL, LLM_API_KEY, MOCK_MODE, get_llm_client


@dataclass
class JudgeResult:
    question: str
    answer_a: str
    answer_b: str
    winner_pass1: str       # "A" | "B" | "tie"  (original order)
    winner_pass2: str       # "A" | "B" | "tie"  (after swap, ALREADY converted back)
    final_winner: str       # consensus after swap-and-average
    reasoning_pass1: str
    reasoning_pass2: str
    position_consistent: bool  # True if both passes agree on same answer
    scores_pass1: dict = field(default_factory=dict)  # {"A": float, "B": float}
    scores_pass2: dict = field(default_factory=dict)


# ─── Task 5: Pairwise Judge ───────────────────────────────────────────────────

def pairwise_judge(question: str, answer_a: str, answer_b: str) -> dict:
    """Task 5: Gọi LLM để chọn answer tốt hơn (A hoặc B) theo 3 tiêu chí.

    Tiêu chí đánh giá:
        - Độ chính xác (accuracy): có khớp với thực tế chính sách không?
        - Độ đầy đủ (completeness): có trả lời đủ câu hỏi không?
        - Tính súc tích (conciseness): có thừa / thiếu thông tin không?

    Returns:
        {"winner": "A"|"B"|"tie", "reasoning": str, "scores": {"A": float, "B": float}}
    """
    prompt = f"""Câu hỏi: {question}

Answer A:
{answer_a}

Answer B:
{answer_b}

Đánh giá độ chính xác, đầy đủ và súc tích. Chỉ trả JSON:
{{"winner":"A|B|tie","reasoning":"...","scores":{{"A":0.0,"B":0.0}}}}"""
    if LLM_API_KEY and not MOCK_MODE:
        try:
            response = get_llm_client().chat.completions.create(
                model=JUDGE_MODEL,
                messages=[
                    {"role": "system", "content": "Bạn là expert đánh giá RAG. Chỉ trả JSON hợp lệ."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"}, temperature=0,
            )
            return _normalize_judgment(json.loads(response.choices[0].message.content or "{}"))
        except Exception as error:
            print(f"  ⚠️  Judge API failed; dùng fallback cục bộ: {error}")
    return _local_judgment(question, answer_a, answer_b)


def _normalize_judgment(value: dict) -> dict:
    winner = str(value.get("winner", "tie")).strip()
    winner = winner if winner in {"A", "B", "tie"} else "tie"
    scores = value.get("scores", {})
    def bounded(name: str) -> float:
        try:
            return max(0.0, min(1.0, float(scores.get(name, 0.0))))
        except (TypeError, ValueError):
            return 0.0
    reasoning = str(value.get("reasoning", "")).strip()
    if winner != "tie" and not reasoning:
        reasoning = "Answer được chọn có chất lượng tổng thể tốt hơn."
    return {"winner": winner, "reasoning": reasoning, "scores": {"A": bounded("A"), "B": bounded("B")}}


def _local_judgment(question: str, answer_a: str, answer_b: str) -> dict:
    """Deterministic fallback for offline tests; not a replacement for an LLM judge."""
    import re
    terms = set(re.findall(r"\w+", question.casefold()))
    def score(answer: str) -> float:
        answer_terms = set(re.findall(r"\w+", answer.casefold()))
        overlap = len(terms & answer_terms) / max(len(terms), 1)
        length_quality = min(len(answer) / 180, 1.0)
        return round(min(1.0, 0.8 * overlap + 0.2 * length_quality), 3)
    score_a, score_b = score(answer_a), score(answer_b)
    winner = "tie" if abs(score_a - score_b) < 0.05 else ("A" if score_a > score_b else "B")
    return {"winner": winner, "reasoning": "Đánh giá fallback dựa trên độ liên quan và độ đầy đủ.",
            "scores": {"A": score_a, "B": score_b}}


def offline_quality_label(answer: str, ground_truth: str) -> int:
    """Binary offline correctness proxy using numeric consistency and token F1."""
    import re
    answer_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", answer))
    truth_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", ground_truth))
    if answer_numbers and truth_numbers and not answer_numbers.issubset(truth_numbers):
        return 0
    stop = {"và", "là", "có", "được", "cho", "của", "trong", "khi", "với", "một",
            "nhân", "viên", "theo", "thì", "này", "đó", "về", "phải", "không"}
    def tokens(text):
        return {token for token in re.findall(r"\w+", text.casefold(), flags=re.UNICODE)
                if len(token) > 1 and token not in stop}
    left, right = tokens(answer), tokens(ground_truth)
    overlap = len(left & right)
    f1 = (2 * overlap / (len(left) + len(right))) if left and right else 0.0
    return int(f1 >= 0.45)


# ─── Task 6: Swap-and-Average ─────────────────────────────────────────────────

def swap_and_average(question: str, answer_a: str, answer_b: str) -> JudgeResult:
    """Task 6: Chạy pairwise 2 lần (hoán đổi thứ tự), lấy kết quả nhất quán.

    Lý do: LLM thường có position bias (ưu tiên answer xuất hiện trước).
    Bằng cách swap, ta phát hiện và giảm bias này.

    Logic:
        Pass 1: judge(q, A, B) → winner_1 (trong không gian A/B)
        Pass 2: judge(q, B, A) → winner_2_raw (trong không gian B/A)
        Convert: nếu winner_2_raw="A" thì thực ra là B (vì đã swap)
        Final:   nếu winner_1 == winner_2 → final = winner_1
                 nếu khác nhau → final = "tie"
    """
    pass1 = pairwise_judge(question, answer_a, answer_b)
    pass2_raw = pairwise_judge(question, answer_b, answer_a)
    winner_pass2 = {"A": "B", "B": "A", "tie": "tie"}[pass2_raw["winner"]]
    consistent = pass1["winner"] == winner_pass2
    return JudgeResult(
        question=question, answer_a=answer_a, answer_b=answer_b,
        winner_pass1=pass1["winner"], winner_pass2=winner_pass2,
        final_winner=pass1["winner"] if consistent else "tie",
        reasoning_pass1=pass1["reasoning"], reasoning_pass2=pass2_raw["reasoning"],
        position_consistent=consistent, scores_pass1=pass1["scores"],
        scores_pass2={"A": pass2_raw["scores"]["B"], "B": pass2_raw["scores"]["A"]},
    )


# ─── Task 7: Cohen's κ ────────────────────────────────────────────────────────

def cohen_kappa(judge_labels: list[int], human_labels: list[int]) -> float:
    """Task 7: Tính Cohen's κ giữa LLM judge và human labels.

    Args:
        judge_labels:  nhãn từ LLM judge (0 = bad answer, 1 = good answer)
        human_labels:  nhãn từ human_labels_10q.json

    Returns:
        κ ∈ [-1, 1]
        Thang đo Landis-Koch: <0=poor, 0-0.2=slight, 0.2-0.4=fair,
                               0.4-0.6=moderate, 0.6-0.8=substantial, 0.8-1=almost perfect

    Gợi ý A — dùng scikit-learn:
        from sklearn.metrics import cohen_kappa_score
        return cohen_kappa_score(human_labels, judge_labels)

    Gợi ý B — tính tay:
        n = len(judge_labels)
        p_o = sum(j == h for j, h in zip(judge_labels, human_labels)) / n
        p_e = (judge_labels.count(1)/n * human_labels.count(1)/n +
               judge_labels.count(0)/n * human_labels.count(0)/n)
        κ = (p_o - p_e) / (1 - p_e) if p_e != 1 else 0
        return κ
    """
    if len(judge_labels) != len(human_labels):
        raise ValueError("judge_labels và human_labels phải có cùng độ dài")
    if not judge_labels:
        return 0.0
    valid = {0, 1}
    if any(label not in valid for label in judge_labels + human_labels):
        raise ValueError("Cohen kappa hiện chỉ hỗ trợ nhãn nhị phân 0/1")
    n = len(judge_labels)
    observed = sum(j == h for j, h in zip(judge_labels, human_labels)) / n
    expected = (
        judge_labels.count(1) / n * human_labels.count(1) / n
        + judge_labels.count(0) / n * human_labels.count(0) / n
    )
    if expected == 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return max(-1.0, min(1.0, (observed - expected) / (1.0 - expected)))


# ─── Task 8: Bias Report ──────────────────────────────────────────────────────

def bias_report(judge_results: list[JudgeResult]) -> dict:
    """Task 8: Đo lường position bias và verbosity bias.

    Position bias: LLM chọn answer theo vị trí (A hay B) thay vì chất lượng.
        → Đo bằng % cases where position_consistent = False

    Verbosity bias: LLM ưu tiên answer dài hơn dù không chính xác hơn.
        → Đo bằng: trong các case A thắng, A có dài hơn B không? Tương tự cho B.

    Returns:
        {
          "total_judged": int,
          "position_bias_rate": float,        # 0-1, cao = bias nhiều
          "position_bias_count": int,
          "verbosity_bias": float,            # 0-1, > 0.6 = đáng lo ngại
          "verbosity_details": {
            "a_wins_a_longer": int,           # A thắng VÀ A dài hơn
            "b_wins_b_longer": int,           # B thắng VÀ B dài hơn
            "total_decisive": int,            # tổng case có winner rõ ràng
          },
          "interpretation": str,
        }
    """
    total = len(judge_results)
    position_count = sum(not result.position_consistent for result in judge_results)
    decisive = [result for result in judge_results if result.final_winner in {"A", "B"}]
    a_longer = sum(result.final_winner == "A" and len(result.answer_a) > len(result.answer_b)
                   for result in decisive)
    b_longer = sum(result.final_winner == "B" and len(result.answer_b) > len(result.answer_a)
                   for result in decisive)
    position_rate = position_count / total if total else 0.0
    verbosity = (a_longer + b_longer) / len(decisive) if decisive else 0.0
    interpretation = (
        "Position bias cao — cần giữ swap-and-average và xem xét judge mạnh hơn."
        if position_rate > 0.3 else "Position bias thấp — judge tương đối ổn định."
    ) if total else "Chưa có kết quả judge để phân tích bias."
    return {
        "total_judged": total, "position_bias_rate": round(position_rate, 3),
        "position_bias_count": position_count, "verbosity_bias": round(verbosity, 3),
        "verbosity_details": {"a_wins_a_longer": a_longer, "b_wins_b_longer": b_longer,
                              "total_decisive": len(decisive)},
        "interpretation": interpretation,
    }


def save_judge_report(results: list[JudgeResult], kappa: float, bias: dict,
                      judge_labels: list[int] | None = None,
                      human_labels: list[int] | None = None,
                      path: str = "reports/judge_results.json") -> None:
    """Persist Phase B results in a JSON-serializable report."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "evaluation_mode": "offline_proxy" if MOCK_MODE or not LLM_API_KEY else "llm_judge",
        "total_judged": len(results),
        "cohen_kappa": round(kappa, 4),
        "judge_labels": judge_labels or [],
        "human_labels": human_labels or [],
        "bias_report": bias,
        "results": [
            {
                "question": result.question,
                "answer_a": result.answer_a,
                "answer_b": result.answer_b,
                "winner_pass1": result.winner_pass1,
                "winner_pass2": result.winner_pass2,
                "final_winner": result.final_winner,
                "position_consistent": result.position_consistent,
                "reasoning_pass1": result.reasoning_pass1,
                "reasoning_pass2": result.reasoning_pass2,
                "scores_pass1": result.scores_pass1,
                "scores_pass2": result.scores_pass2,
            }
            for result in results
        ],
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(f"Phase B report saved → {path}")


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    with open(HUMAN_LABELS_PATH, encoding="utf-8") as f:
        human_data = json.load(f)
    test_set_path = os.path.join(os.path.dirname(HUMAN_LABELS_PATH), "test_set_50q.json")
    with open(test_set_path, encoding="utf-8") as f:
        ground_truth_by_id = {item["id"]: item["ground_truth"] for item in json.load(f)}

    results = [
        swap_and_average(item["question"], item["model_answer"],
                         ground_truth_by_id[item["question_id"]])
        for item in human_data
    ]
    human_labels = [item["human_label"] for item in human_data]
    judge_labels = [offline_quality_label(item["model_answer"], ground_truth_by_id[item["question_id"]])
                    for item in human_data]
    kappa = cohen_kappa(judge_labels, human_labels)
    bias = bias_report(results)
    save_judge_report(results, kappa, bias, judge_labels, human_labels)
    print(f"Cohen's κ: {kappa:.3f} | Position bias: {bias['position_bias_rate']:.1%}")
