"""Verifier les lignes destinees a BigQuery sans connexion reseau."""

from scripts.seed_bigquery import build_rows


def test_seed_count_and_citations():
    rows = build_rows()
    assert len(rows) == 7
    assert len({r["citation"] for r in rows}) == len(rows)


def test_seed_preserves_acl_and_effective_dates():
    confidential = next(r for r in build_rows() if r["clause_id"] == "CONF-01")
    assert confidential["allowed_groups"] == ["superviseurs_auto"]
    assert confidential["effective_from"] == "2026-01-01"


def test_seed_search_text_is_normalized():
    rows = build_rows()
    assert all("search_text" in r for r in rows)
    assert all(r["title"].split(" ")[0].lower() in r["search_text"] for r in rows)
