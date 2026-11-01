"""Charger les clauses fictives du lot 1 dans BigQuery.

Execution volontairement protegee par --execute.
Le script n'ecrit QUE dans autoclaim_mvp.contract_clauses_demo du projet
explicitement fourni. La table de demonstration est REMPLACEE a chaque seed.
"""

import argparse
from pathlib import Path
import json

from autoclaim_agent.retrieval import BigQueryClauseRetriever, normalize

ROOT = Path(__file__).resolve().parents[1]


def build_rows(*, include_documents: bool = False, include_images: bool = False) -> list[dict]:
    """Preparer une ligne par clause, en preservant les dates et les ACL."""
    rows = []
    source = ROOT / "contracts" / "clauses.jsonl"
    for line in source.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        clause = json.loads(line)
        # La colonne SEARCH est une projection calculable ; la source reste
        # intacte. Le contenu reste entier car nos clauses sont courtes.
        clause["search_text"] = normalize(
            f"{clause['title']} {clause['coverage_code']} {clause['text']}"
        )
        rows.append(clause)
    if include_documents:
        # Never index unapproved uploads. Rows originate from the approved
        # offline extraction job and retain ACL and effective dates.
        index_path = ROOT / "contracts" / "ingested_documents.jsonl"
        if not index_path.is_file():
            raise FileNotFoundError("Generate the document index before seeding BigQuery")
        for line in index_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                doc = json.loads(line)
                if doc["clause_type"] != "document_excerpt":
                    raise ValueError("Unexpected document index row")
                rows.append(doc)
        if len({row["citation"] for row in rows}) != len(rows):
            raise ValueError("Duplicate citations in dataset")
    if include_images and not include_documents:
        raise ValueError("Inclure les PDF/DOCX lors du rechargement de la table fictive")
    if include_images:
        # Images are only indexed AFTER an explicit Gemini OCR + human review.
        # Never implicitly infer OCR text from an unreviewed image.
        source = ROOT / "contracts" / "ingested_images.jsonl"
        if not source.is_file():
            raise FileNotFoundError("OCR non valide : lancer scripts.ingest_images --execute puis --approve")
        for line in source.read_text(encoding="utf-8").splitlines():
            if line.strip():
                image = json.loads(line)
                if image["clause_type"] != "document_excerpt":
                    raise ValueError("Type image invalide")
                rows.append(image)
    if len({row["citation"] for row in rows}) != len(rows):
        raise ValueError("Citations en doublon")
    if not rows:
        raise ValueError("Aucune clause a charger")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed BigQuery AutoClaim (donnees fictives)")
    parser.add_argument("--project", required=True, help="Projet GCP de TEST (avec facturation)")
    parser.add_argument("--location", default="europe-west1")
    parser.add_argument("--execute", action="store_true", help="Autoriser le chargement facturable")
    parser.add_argument("--include-documents", action="store_true", help="Inclure le corpus PDF/DOCX approuve")
    parser.add_argument("--include-images", action="store_true", help="Inclure OCR image apres validation humaine")
    args = parser.parse_args()

    retriever = BigQueryClauseRetriever(args.project, location=args.location)
    rows = build_rows(include_documents=args.include_documents, include_images=args.include_images)
    print(f"Cible : {retriever.table_id} ({args.location})")
    print(f"Clauses et extraits documentaires fictifs : {len(rows)}")
    print("ATTENTION : cette commande remplace la table de demonstration cible.")
    if not args.execute:
        print("DRY RUN : ajouter --execute pour creer le dataset et charger les clauses.")
        return

    # Import au dernier moment pour que le dry run fonctionne hors GCP.
    from google.cloud import bigquery

    client = bigquery.Client(project=args.project, location=args.location)
    dataset = bigquery.Dataset(f"{args.project}.{retriever.DATASET}")
    dataset.location = args.location
    client.create_dataset(dataset, exists_ok=True)

    schema = [
        bigquery.SchemaField("clause_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("document_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("version", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("section", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("title", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("coverage_code", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("clause_type", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("text", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("allowed_groups", "STRING", mode="REPEATED"),
        bigquery.SchemaField("effective_from", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("effective_to", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("citation", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("search_text", "STRING", mode="REQUIRED"),
    ]

    config = bigquery.LoadJobConfig(
        schema=schema,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    job = client.load_table_from_json(
        rows, retriever.table_id, job_config=config, location=args.location
    )
    job.result(timeout=120)
    table = client.get_table(retriever.table_id)
    print(f"OK : {table.num_rows} clauses chargees dans {retriever.table_id}")
    print("Pas d'index cree pour ce corpus minuscule ; SEARCH fonctionne sans index.")


if __name__ == "__main__":
    main()
