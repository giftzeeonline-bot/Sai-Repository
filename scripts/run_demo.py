#!/usr/bin/env python3
"""Exercise the local HTTP API with 10 saved queries and persist responses."""

import json
import os
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import server  # noqa: E402


def request_json(url, payload=None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"} if body else {},
        method="GET" if body is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    cases = json.loads((ROOT / "data/demo_queries.json").read_text(encoding="utf-8"))["queries"]
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    base_url = f"http://127.0.0.1:{httpd.server_port}"
    previous_model = os.environ.get("OLLAMA_MODEL")
    os.environ["OLLAMA_MODEL"] = ""
    thread.start()
    try:
        with urllib.request.urlopen(base_url + "/", timeout=5) as response:
            page = response.read().decode("utf-8")
        if "Washing Machine Support Triage" not in page:
            raise RuntimeError("The local UI route did not return the expected page.")
        status = request_json(base_url + "/api/status")
        captured = []
        for case in cases:
            started = time.perf_counter()
            response = request_json(base_url + "/api/search", case)
            round_trip_ms = round((time.perf_counter() - started) * 1000, 1)
            captured.append({
                "name": case["name"],
                "request": case,
                "response": response,
                "round_trip_ms": round_trip_ms,
            })
        output = {
            "metadata": {
                "description": "Fictional demo; captured through the local HTTP API.",
                "corpus_records": status["corpus_size"],
                "model_mode": "extractive (deterministic demo)",
                "jira_configured": status["jira_configured"],
            },
            "results": captured,
        }
        output_path = ROOT / "data/demo_responses.json"
        output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        for item in captured:
            ids = [match["id"] for match in item["response"]["matches"]]
            action = "new-ticket eligible" if item["response"]["can_create"] else "existing Jira match"
            print(f"{item['name']}: {ids or 'no evidence'} | {action} | {item['round_trip_ms']} ms")
        print(f"Saved {len(captured)} responses to {output_path.relative_to(ROOT)}")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)
        if previous_model is None:
            os.environ.pop("OLLAMA_MODEL", None)
        else:
            os.environ["OLLAMA_MODEL"] = previous_model


if __name__ == "__main__":
    main()
