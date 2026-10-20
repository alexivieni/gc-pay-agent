"""Check that eval/questions.yaml is well-formed. Runs in CI on every push.

    python eval/check_questions.py

Fails if an id is duplicated, a type is unknown, or a required field is missing.
Unverified expected answers are reported but don't fail the check.
"""

import pathlib
import sys

import yaml

QUESTIONS = pathlib.Path(__file__).resolve().parent / "questions.yaml"

REQUIRED = {
    "answer": ["id", "type", "agreement", "question", "expected", "article", "reference", "source"],
    "clarify": ["id", "type", "question", "expected"],
    "refuse": ["id", "type", "question", "expected"],
}


def main() -> None:
    questions = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    if not isinstance(questions, list) or not questions:
        sys.exit("questions.yaml must be a non-empty list of questions.")

    problems, seen = [], set()
    for number, q in enumerate(questions, 1):
        label = q.get("id") or f"entry {number}"
        if q.get("id") in seen:
            problems.append(f"{label}: duplicate id")
        seen.add(q.get("id"))
        kind = q.get("type")
        if kind not in REQUIRED:
            problems.append(f"{label}: unknown type {kind!r} (use answer, clarify or refuse)")
            continue
        missing = [field for field in REQUIRED[kind] if not q.get(field)]
        if missing:
            problems.append(f"{label}: missing {', '.join(missing)}")

    unverified = [q["id"] for q in questions if not q.get("verified")]
    counts = {kind: sum(1 for q in questions if q.get("type") == kind) for kind in REQUIRED}
    print(f"{len(questions)} questions: " + ", ".join(f"{n} {kind}" for kind, n in counts.items()))
    if unverified:
        print(f"{len(unverified)} not verified yet: {', '.join(unverified)}")

    if problems:
        print("\nProblems:\n  " + "\n  ".join(problems))
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
