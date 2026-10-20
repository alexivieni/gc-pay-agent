"""Evaluate the agent against the test set in eval/questions.yaml.

Asks the agent every question, grades each answer against the expected answer,
checks citations, and reports accuracy, response time and cost.

    python eval/run_eval.py                    # every question
    python eval/run_eval.py --type answer      # one kind: answer, clarify or refuse
    python eval/run_eval.py --ids pa-01 it-06  # specific questions

Results are saved in eval/results/ as <timestamp>.jsonl (every answer) and
<timestamp>.md (the summary).
"""

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import time

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from common import agent_name, ask, cited_files, clients, setting  # noqa: E402

QUESTIONS = ROOT / "eval" / "questions.yaml"
INSTRUCTIONS = ROOT / "agent" / "instructions.md"
RESULTS_DIR = ROOT / "eval" / "results"

# Azure list prices for gpt-5-mini, in US dollars per million tokens.
# Pass --input-price / --output-price if you evaluate a different model.
INPUT_PRICE = 0.275
OUTPUT_PRICE = 2.20

JUDGE_PROMPT = """You are grading an AI assistant's answer to a question about Government of Canada collective agreements.

Question: {question}
Expected behaviour type: {type}
Reference (checked by a person): {expected}
Assistant's answer: {answer}

How to grade:
- type "answer": "correct" if the answer states the same facts as the reference (same numbers, rates and conditions; wording can differ). Extra details are fine unless they contradict the reference. "partial" if it is mostly right but misses or blurs a key condition. "incorrect" if a key fact is wrong or missing, or if it doesn't answer.
- type "clarify": "correct" if it asks which agreement, group or details apply, or answers separately for each relevant agreement. "incorrect" if it gives one answer as if it applied to everyone.
- type "refuse": "correct" if it says the agreements it has don't cover this and doesn't invent an answer. "incorrect" if it answers from outside the agreements.

Reply with JSON only, no other text:
{{"verdict": "correct" | "partial" | "incorrect", "reason": "<one short sentence>"}}"""


def load_questions(args) -> list[dict]:
    questions = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    if args.ids:
        wanted = set(args.ids)
        questions = [q for q in questions if q["id"] in wanted]
    if args.type:
        questions = [q for q in questions if q["type"] == args.type]
    if not questions:
        sys.exit("No questions matched.")
    return questions


def token_counts(response) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    return (getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0)


def cites_article(answer: str, article: str) -> bool:
    """True if the answer mentions the article, e.g. 'Article 28' or clause '28.05'."""
    pattern = rf"(?:article|clause|art\.?)\s*{article}\b|\b{article}\.\d{{2}}"
    return re.search(pattern, answer, re.IGNORECASE) is not None


def grade(openai, model: str, question: dict, answer: str) -> tuple[str, str, int, int]:
    prompt = JUDGE_PROMPT.format(
        question=question["question"], type=question["type"],
        expected=question["expected"], answer=answer or "(no answer)",
    )
    response = openai.responses.create(model=model, input=prompt)
    tokens_in, tokens_out = token_counts(response)
    match = re.search(r"\{.*\}", response.output_text or "", re.DOTALL)
    try:
        result = json.loads(match.group(0))
        verdict = str(result.get("verdict", "")).strip().lower()
        reason = str(result.get("reason", "")).strip()
    except (AttributeError, ValueError):
        verdict, reason = "error", f"Couldn't read the grader's reply: {response.output_text!r}"
    if verdict not in {"correct", "partial", "incorrect"}:
        verdict, reason = "error", reason or "Unexpected verdict"
    return verdict, reason, tokens_in, tokens_out


def cost(tokens_in: int, tokens_out: int, args) -> float:
    return tokens_in / 1e6 * args.input_price + tokens_out / 1e6 * args.output_price


def git_commit() -> str:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "agent/instructions.md"], cwd=ROOT,
                               capture_output=True, text=True).stdout.strip()
        return (commit or "no commits") + (" (instructions changed since commit)" if dirty else "")
    except OSError:
        return "git not available"


def evaluate(openai, question: dict, model: str, args) -> dict:
    record = {k: question.get(k) for k in ("id", "type", "agreement", "question", "expected", "verified")}
    started = time.perf_counter()
    try:
        response = ask(openai, question["question"])
        record["latency_s"] = round(time.perf_counter() - started, 2)
        record["answer"] = response.output_text or ""
        record["cited"] = cited_files(openai, response)
        tokens_in, tokens_out = token_counts(response)
    except Exception as err:  # keep going; one failed question shouldn't stop the run
        record.update(answer="", cited=[], verdict="error", reason=f"{type(err).__name__}: {err}",
                      latency_s=round(time.perf_counter() - started, 2), citation_ok=None,
                      input_tokens=0, output_tokens=0, cost_usd=0.0, judge_cost_usd=0.0)
        return record

    record.update(input_tokens=tokens_in, output_tokens=tokens_out,
                  cost_usd=round(cost(tokens_in, tokens_out, args), 6))

    if question["type"] == "answer":
        record["citation_ok"] = (question["source"] in record["cited"]
                                 and cites_article(record["answer"], str(question["article"])))
    else:
        record["citation_ok"] = None

    try:
        verdict, reason, judge_in, judge_out = grade(openai, model, question, record["answer"])
    except Exception as err:
        verdict, reason, judge_in, judge_out = "error", f"Grading failed: {type(err).__name__}: {err}", 0, 0
    record.update(verdict=verdict, reason=reason,
                  judge_cost_usd=round(cost(judge_in, judge_out, args), 6))
    return record


def summarize(records: list[dict], meta: dict) -> str:
    def count(kind: str, verdict: str) -> int:
        return sum(1 for r in records if r["type"] == kind and r["verdict"] == verdict)

    def total(kind: str) -> int:
        return sum(1 for r in records if r["type"] == kind)

    def pct(n: int, d: int) -> str:
        return f"{n} / {d} ({n / d:.0%})" if d else "n/a"

    answered = [r for r in records if r.get("answer")]
    answer_total = total("answer")
    cited = sum(1 for r in records if r["type"] == "answer" and r.get("citation_ok"))
    avg_latency = sum(r["latency_s"] for r in answered) / len(answered) if answered else 0
    agent_cost = sum(r["cost_usd"] for r in records)
    judge_cost = sum(r["judge_cost_usd"] for r in records)
    unverified = sum(1 for r in records if not r.get("verified"))

    lines = [
        f"# Evaluation run {meta['started']}",
        "",
        f"Agent `{meta['agent']}` · model `{meta['model']}` · commit `{meta['commit']}` · "
        f"instructions `{meta['instructions']}`",
        "",
        "| Metric | Result |",
        "| --- | --- |",
        f"| Answers correct | {pct(count('answer', 'correct'), answer_total)} |",
        f"| Answers partially correct | {count('answer', 'partial')} |",
        f"| Cited the right document and article | {pct(cited, answer_total)} |",
        f"| Asked for missing details when needed | {pct(count('clarify', 'correct'), total('clarify'))} |",
        f"| Declined out-of-scope questions | {pct(count('refuse', 'correct'), total('refuse'))} |",
        f"| Average response time | {avg_latency:.1f} s |",
        f"| Average cost per answer | ${(agent_cost / len(answered)) if answered else 0:.4f} |",
        f"| Total cost | ${agent_cost:.2f} (plus ${judge_cost:.2f} for grading) |",
        "",
    ]
    if unverified:
        lines += [f"> {unverified} expected answers aren't verified yet, so treat these results as provisional.", ""]

    problems = [r for r in records if r["verdict"] != "correct"
                or (r["type"] == "answer" and not r.get("citation_ok"))]
    if problems:
        lines += ["## Needs attention", "", "| Question | Verdict | Cited correctly | Why |", "| --- | --- | --- | --- |"]
        for r in problems:
            cited_text = "n/a" if r.get("citation_ok") is None else ("yes" if r["citation_ok"] else "no")
            reason = (r.get("reason") or "").replace("|", "/")
            lines.append(f"| {r['id']} | {r['verdict']} | {cited_text} | {reason} |")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ids", nargs="+", help="only these question ids")
    parser.add_argument("--type", choices=["answer", "clarify", "refuse"], help="only this kind of question")
    parser.add_argument("--input-price", type=float, default=INPUT_PRICE, help="USD per million input tokens")
    parser.add_argument("--output-price", type=float, default=OUTPUT_PRICE, help="USD per million output tokens")
    args = parser.parse_args()

    questions = load_questions(args)
    _, openai = clients()
    if hasattr(openai, "with_options"):
        openai = openai.with_options(max_retries=5)  # ride out brief rate limits
    model = setting("MODEL_DEPLOYMENT")

    started = dt.datetime.now()
    meta = {
        "started": started.strftime("%Y-%m-%d %H:%M"),
        "agent": agent_name(),
        "model": model,
        "commit": git_commit(),
        "instructions": hashlib.sha256(INSTRUCTIONS.read_bytes()).hexdigest()[:8],
    }

    print(f"Evaluating {len(questions)} questions against agent '{meta['agent']}'\n")
    records = []
    for i, question in enumerate(questions, 1):
        record = evaluate(openai, question, model, args)
        records.append(record)
        cite = "" if record.get("citation_ok") is None else ("  cited" if record["citation_ok"] else "  NOT cited")
        print(f"[{i:2}/{len(questions)}] {record['id']:<6} {record['verdict']:<9} {record['latency_s']:5.1f}s{cite}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%d-%H%M%S")
    with (RESULTS_DIR / f"{stamp}.jsonl").open("w", encoding="utf-8") as out:
        for record in records:
            out.write(json.dumps({**record, **{"run": meta}}, ensure_ascii=False) + "\n")
    summary = summarize(records, meta)
    (RESULTS_DIR / f"{stamp}.md").write_text(summary, encoding="utf-8")

    print("\n" + summary)
    print(f"Saved eval/results/{stamp}.jsonl and eval/results/{stamp}.md")


if __name__ == "__main__":
    main()
