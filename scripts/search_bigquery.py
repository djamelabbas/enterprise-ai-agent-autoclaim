"""CLI de DEMONSTRATION - ne pas exposer tel quel comme API/outil ADK.

Le drapeau --simulate-group est une simulation de role, PAS une
verification d'identite. L'etape de securite integrera IAP/Cloud Identity.
"""

import argparse

from autoclaim_agent.retrieval import BigQueryClauseRetriever


def main() -> None:
    parser = argparse.ArgumentParser(description="Recherche BigQuery de clauses fictives")
    parser.add_argument("--project", required=True)
    parser.add_argument("--location", default="europe-west1")
    parser.add_argument("--query", required=True)
    parser.add_argument("--event-date", default="2026-10-20")
    parser.add_argument("--coverage", choices=["BRIS_GLACE", "VOL", "DTA", "ALL"])
    parser.add_argument("--simulate-group", required=True,
                        choices=["gestionnaires_auto", "superviseurs_auto"])
    args = parser.parse_args()

    print("MODE DEMO : groupes simules, ne constitue PAS un test IAM/IAP.")
    retriever = BigQueryClauseRetriever(args.project, location=args.location)
    rows = retriever.search(
        args.query,
        verified_groups=frozenset({args.simulate_group}),
        event_date=args.event_date,
        coverage_code=args.coverage,
    )
    if not rows:
        print("Aucune clause accessible correspondant a la recherche.")
    for row in rows:
        print(f"\n{row['citation']} | score lexical={row['score']}")
        print(f"{row['title']}: {row['text']}")


if __name__ == "__main__":
    main()
