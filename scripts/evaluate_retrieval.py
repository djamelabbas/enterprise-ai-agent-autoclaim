"""Benchmark grounded in gold citation IDs, with offline deterministic stub mode.

Execute after semantic index creation; output is comparative metrics, not
an assertion that a given search method is better. Never logs raw queries.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from autoclaim_agent.hybrid import HybridClauseRetriever
from autoclaim_agent.retrieval import BigQueryClauseRetriever, LocalClauseRetriever

ROOT = Path(__file__).resolve().parents[1]


def metrics(samples: list[dict], results: list[list[str]], *, k: int = 5) -> dict:
    if len(samples) != len(results) or not samples:
        raise ValueError("Echantillons invalides")
    hits, reciprocal_ranks, leaks = [], [], 0
    for sample, citations in zip(samples, results):
        top = list(citations[:k])
        expected = set(sample.get("expected", []))
        forbidden = set(sample.get("forbidden", []))
        if expected:
            hits.append(float(bool(expected.intersection(top))))
            ranks = [i for i, item in enumerate(top, 1) if item in expected]
            reciprocal_ranks.append(1 / min(ranks) if ranks else 0.0)
        leaks += len(forbidden.intersection(top))
    return {
        "evaluated_questions": len(samples),
        "expected_questions": len(hits),
        "hit_at_5": round(sum(hits) / len(hits), 3) if hits else None,
        "mrr_at_5": round(sum(reciprocal_ranks) / len(reciprocal_ranks), 3) if reciprocal_ranks else None,
        "forbidden_citation_count": leaks,
    }


def evaluate(retriever, samples: list[dict], *, k: int = 5) -> tuple[dict, list[dict]]:
    results, cases = [], []
    for sample in samples:
        rows = retriever.search(
            sample["question"], verified_groups=frozenset(sample["groups"]),
            event_date=sample["event_date"], coverage_code=sample["coverage_code"], limit=k,
        )
        refs = [r["citation"] for r in rows]
        results.append(refs)
        cases.append({"id": sample["id"], "retrieved": refs, "expected": sample.get("expected", [])})
    return metrics(samples, results, k=k), cases


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("lexical", "semantic", "hybrid", "compare", "offline"), default="offline")
    parser.add_argument("--project", help="Requis pour les requetes GCP")
    parser.add_argument("--location", default="europe-west1")
    parser.add_argument("--out", help="JSON local optionnel, hors git")
    args = parser.parse_args()
    samples = json.loads((ROOT / "data" / "retrieval_golden.json").read_text(encoding="utf-8"))
    if args.mode != "offline" and not args.project:
        parser.error("--project est requis pour le benchmark cloud")
    modes = ("lexical", "semantic", "hybrid") if args.mode == "compare" else (args.mode,)
    report = {"corpus": "AutoClaim fictif", "metrics": {}, "details": {}}
    for mode in modes:
        if mode == "offline":
            retriever = LocalClauseRetriever()  # offline corpus has 7 CG only
        elif mode == "lexical":
            retriever = BigQueryClauseRetriever(args.project, location=args.location)
        else:
            retriever = HybridClauseRetriever(args.project, location=args.location, mode=mode)
        summary, cases = evaluate(retriever, samples)
        report["metrics"][mode] = summary
        report["details"][mode] = cases
        print(f"{mode}: {summary}")
    if args.out:
        path = Path(args.out)
        if not path.parent.exists():
            raise ValueError("Repertoire de sortie absent")
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Rapport ecrit localement (verifier le contenu avant tout partage).")

if __name__ == "__main__":
    main()
