#!/usr/bin/env python3
"""Evaluate retrieval against the tiny fictional, hand-labeled smoke set."""

import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from server import CORPUS, citation, rank  # noqa: E402


def percentile95(values):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def main():
    cases = json.loads((ROOT / "evaluation/golden_queries.json").read_text())["queries"]
    ticket_precisions, ticket_recalls = [], []
    manual_precisions, manual_recalls = [], []
    timings = []
    valid_citations = total_citations = 0
    for case in cases:
        started = time.perf_counter()
        results = [item for item in rank(case["query"], limit=8) if item["relevance"] >= 10]
        timings.append((time.perf_counter() - started) * 1000)
        for kind, expected_key, precisions, recalls in (
            ("ticket", "expected_ticket_ids", ticket_precisions, ticket_recalls),
            ("manual", "expected_manual_ids", manual_precisions, manual_recalls),
        ):
            expected = set(case[expected_key])
            found = {item["id"] for item in results if item["kind"] == kind}
            precisions.append(len(found & expected) / max(1, len(found)))
            recalls.append(len(found & expected) / max(1, len(expected)))
        for item in results:
            total_citations += 1
            known_source = any(doc["id"] == item["id"] for doc in CORPUS)
            valid_citations += known_source and citation(item)["id"] == item["id"]
        print(f"{case['query']}: {[item['id'] for item in results]}")
    print(f"Ticket Precision@3: {sum(ticket_precisions) / len(ticket_precisions):.1%}")
    print(f"Ticket Recall@3: {sum(ticket_recalls) / len(ticket_recalls):.1%}")
    print(f"Manual Precision@3: {sum(manual_precisions) / len(manual_precisions):.1%}")
    print(f"Manual Recall@3: {sum(manual_recalls) / len(manual_recalls):.1%}")
    print(f"Citation ID validity: {valid_citations / max(1, total_citations):.1%}")
    print(f"Retrieval p95: {percentile95(timings):.1f} ms")
    print("Note: retrieval smoke metrics are not end-to-end accuracy or production results.")


if __name__ == "__main__":
    main()
