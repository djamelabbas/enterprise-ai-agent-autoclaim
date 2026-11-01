"""Parameterized EUR estimate; NEVER present as actual Cloud Billing charge."""
import argparse

def estimate(input_tokens: int, output_tokens: int, input_eur_per_million: float, output_eur_per_million: float) -> float:
    if min(input_tokens, output_tokens, input_eur_per_million, output_eur_per_million) < 0:
        raise ValueError("Valeur negative")
    return round((input_tokens * input_eur_per_million + output_tokens * output_eur_per_million) / 1_000_000, 6)

def main():
    p = argparse.ArgumentParser(description="Estimation configurable, pas facturation reelle")
    p.add_argument("--input-tokens", type=int, required=True)
    p.add_argument("--output-tokens", type=int, required=True)
    p.add_argument("--input-eur-per-million", type=float, required=True)
    p.add_argument("--output-eur-per-million", type=float, required=True)
    x = p.parse_args()
    cost = estimate(x.input_tokens, x.output_tokens, x.input_eur_per_million, x.output_eur_per_million)
    print(f"Estimation indicative : {cost:.6f} EUR (hors cache, embeddings, BigQuery, taxes et autres SKUs)")

if __name__ == "__main__": main()
