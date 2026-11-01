"""Deterministic business regression on fictitious golden cases (NO LLM call).

This complements, but does NOT replace, factuality/faithfulness evaluation of
LLM-generated explanations. Run both retrieval and business checks prior to a
production-like deployment.
"""
from __future__ import annotations
import json
from pathlib import Path

from autoclaim_agent.coverage import analyze_coverage
from autoclaim_agent.security import VerifiedPrincipal

ROOT = Path(__file__).resolve().parents[1]


def run():
    cases = json.loads((ROOT / "data" / "expected_cases.json").read_text(encoding="utf-8"))
    successes = []
    for case in cases:
        result = analyze_coverage(case["claim_id"], verified_groups=frozenset({"gestionnaires_auto", "superviseurs_auto"}))
        passed = (result["status"] == case["expected_status"] and
                  result.get("indicative_amount_eur") == case["expected_indicative_amount_eur"])
        successes.append(passed)
    return {"cases": len(cases), "passed": sum(successes), "success_rate": round(sum(successes)/len(cases),3)}


def main():
    result = run()
    print(json.dumps(result))
    if result["passed"] != result["cases"]:
        raise SystemExit(1)

if __name__ == "__main__": main()
