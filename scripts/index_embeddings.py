"""Opt-in construction of the semantic index. NEVER rewrites the clause table.

Dry-run: uv run python -m scripts.index_embeddings --project YOUR_PROJECT
Execute: uv run python -m scripts.index_embeddings --project YOUR_PROJECT --execute
Costs: one Gemini embedding call per passage + BigQuery load/queries.
"""
import argparse
import hashlib

from autoclaim_agent.hybrid import EMBEDDING_DIM, EMBEDDING_MODEL, HybridClauseRetriever, VertexTextEmbedder
from scripts.seed_bigquery import build_rows


def build_embedded_rows(rows, embedder):
    """Version and content fingerprint protect against stale embeddings."""
    records = []
    for row in rows:
        content = f"{row['title']}\n{row['text']}"[:6000]
        vector = embedder.embed(content, task_type="RETRIEVAL_DOCUMENT")
        records.append({
            **{key: row[key] for key in (
                "clause_id", "document_id", "version", "section", "title",
                "coverage_code", "clause_type", "text", "citation",
                "allowed_groups", "effective_from", "effective_to",
            )},
            "embedding": vector,
            "embedding_model": EMBEDDING_MODEL,
            "embedding_dimensions": EMBEDDING_DIM,
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        })
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--include-images", action="store_true", help="Only after verified image index generated")
    parser.add_argument("--location", default="europe-west1")
    args = parser.parse_args()
    retriever = HybridClauseRetriever(args.project, location=args.location)
    rows = build_rows(include_documents=True, include_images=args.include_images)
    print(f"Corpus : {len(rows)} passages; modele : {EMBEDDING_MODEL}; dimensions : {EMBEDDING_DIM}")
    print(f"Table SEMANTIQUE uniquement : {retriever.table_id} ({args.location})")
    if not args.execute:
        print("DRY RUN : aucune requete Gemini ni ecriture BigQuery. Ajouter --execute.")
        return
    from google.cloud import bigquery
    embedded = build_embedded_rows(rows, VertexTextEmbedder(args.project, location=args.location))
    client = bigquery.Client(project=args.project, location=args.location)
    schema = [
        bigquery.SchemaField("clause_id", "STRING"),
        bigquery.SchemaField("document_id", "STRING"),
        bigquery.SchemaField("version", "STRING"),
        bigquery.SchemaField("section", "STRING"),
        bigquery.SchemaField("title", "STRING"),
        bigquery.SchemaField("coverage_code", "STRING"),
        bigquery.SchemaField("clause_type", "STRING"),
        bigquery.SchemaField("text", "STRING"),
        bigquery.SchemaField("citation", "STRING"),
        bigquery.SchemaField("allowed_groups", "STRING", mode="REPEATED"),
        bigquery.SchemaField("effective_from", "DATE"),
        bigquery.SchemaField("effective_to", "DATE"),
        bigquery.SchemaField("embedding", "FLOAT64", mode="REPEATED"),
        bigquery.SchemaField("embedding_model", "STRING"),
        bigquery.SchemaField("embedding_dimensions", "INTEGER"),
        bigquery.SchemaField("content_sha256", "STRING"),
    ]
    config = bigquery.LoadJobConfig(
        schema=schema,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    job = client.load_table_from_json(embedded, retriever.table_id, job_config=config, location=args.location)
    job.result(timeout=180)
    print(f"OK : {len(embedded)} embeddings ecrits dans {retriever.table_id}")

if __name__ == "__main__":
    main()
