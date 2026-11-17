#!/usr/bin/env python3
"""Local, evidence-first support triage UI and API."""

import base64
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STATIC = ROOT / "app" / "index.html"
MIN_RELEVANCE = 10.0
TOKEN_RE = re.compile(r"[a-z0-9]+")
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "cycle", "during",
    "for", "from", "has", "in", "is", "it", "of", "on", "or", "the", "to",
    "was", "with", "washer", "washing", "machine",
}


def load_corpus():
    tickets = json.loads((DATA / "tickets.json").read_text(encoding="utf-8"))["tickets"]
    pages = json.loads((DATA / "manual_chunks.json").read_text(encoding="utf-8"))["pages"]
    docs = []
    for ticket in tickets:
        docs.append({
            "id": ticket["id"],
            "kind": "ticket",
            "title": ticket["summary"],
            "text": " ".join(ticket.get(key, "") for key in ("summary", "component", "observed", "resolution")),
            "component": ticket.get("component", ""),
            "observed": ticket.get("observed", ""),
            "resolution": ticket.get("resolution", ""),
            "status": ticket.get("status", ""),
            "url": ticket.get("url", ""),
        })
    for page in pages:
        docs.append({
            "id": page["id"],
            "kind": "manual",
            "title": page["title"],
            "text": page["text"],
            "page": page["page"],
            "source": page["source"],
        })
    return docs


CORPUS = load_corpus()


def tokens(text):
    return [word for word in TOKEN_RE.findall(text.lower()) if word not in STOP_WORDS]


def rank(query, limit=8):
    query_counts = {}
    for word in tokens(query):
        query_counts[word] = query_counts.get(word, 0) + 1
    if not query_counts:
        return []

    search_corpus = []
    seen_manual_sections = set()
    for doc in CORPUS:
        if doc["kind"] == "manual":
            section = doc["title"].split(":", 1)[0]
            if section in seen_manual_sections:
                continue
            seen_manual_sections.add(section)
        search_corpus.append(doc)

    doc_counts = []
    document_frequency = {}
    for doc in search_corpus:
        counts = {}
        for word in tokens(doc["text"]):
            counts[word] = counts.get(word, 0) + 1
        doc_counts.append(counts)
        for word in counts:
            document_frequency[word] = document_frequency.get(word, 0) + 1

    doc_total = len(search_corpus)
    idf = {
        word: math.log(1 + doc_total / (1 + frequency))
        for word, frequency in document_frequency.items()
    }
    query_vector = {
        word: count * idf.get(word, math.log(1 + doc_total))
        for word, count in query_counts.items()
    }
    query_norm = math.sqrt(sum(weight * weight for weight in query_vector.values()))
    results = []
    for doc, counts in zip(search_corpus, doc_counts):
        vector = {word: count * idf[word] for word, count in counts.items()}
        norm = math.sqrt(sum(weight * weight for weight in vector.values()))
        dot = sum(weight * vector.get(word, 0.0) for word, weight in query_vector.items())
        score = 100 * dot / (query_norm * norm) if norm and query_norm else 0
        if score:
            results.append({**doc, "relevance": round(score, 1)})
    ranked = sorted(results, key=lambda item: (-item["relevance"], item["kind"], item["id"]))
    tickets = [item for item in ranked if item["kind"] == "ticket"][:3]
    manuals = [item for item in ranked if item["kind"] == "manual"][:3]
    balanced = sorted(tickets + manuals, key=lambda item: (-item["relevance"], item["kind"], item["id"]))
    return balanced[:limit]


def citation(item):
    if item["kind"] == "ticket":
        return {"id": item["id"], "label": item["id"], "url": item["url"]}
    return {
        "id": item["id"],
        "label": f"Service manual, page {item['page']} ({item['id']})",
        "url": None,
    }


def evidence_suggestions(results):
    suggestions = []
    for item in results:
        if item["kind"] == "ticket":
            quote = item["resolution"]
        else:
            quote = item["text"]
        if quote:
            suggestions.append({
                "text": quote,
                "citations": [citation(item)],
                "groundedness": 100,
                "relevance": item["relevance"],
            })
        if len(suggestions) == 3:
            break
    return suggestions


def local_model_quotes(query, results):
    if not results:
        return [], {
            "mode": "extractive",
            "notice": "No evidence crossed the relevance threshold; no suggestion was generated.",
        }
    model = os.environ.get("OLLAMA_MODEL", "").strip()
    if not model:
        return evidence_suggestions(results), {
            "mode": "extractive",
            "notice": "Local model is not configured; showing exact source excerpts.",
        }

    evidence = []
    by_id = {}
    for item in results[:6]:
        text = item["resolution"] if item["kind"] == "ticket" else item["text"]
        by_id[item["id"]] = text
        evidence.append({"source_id": item["id"], "text": text})
    prompt = (
        "Select up to 3 useful exact excerpts from the supplied evidence for the query. "
        "Do not paraphrase, add facts, or provide instructions. Return JSON only with "
        'shape {"quotes":[{"source_id":"...","text":"exact copied substring"}]}. '
        f"Query: {query}\nEvidence: {json.dumps(evidence)}"
    )
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "num_predict": 256},
    }).encode()
    request = urllib.request.Request(
        os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
        + "/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            model_response = json.loads(response.read(256 * 1024).decode("utf-8"))
        generated = json.loads(model_response.get("response", ""))
        quotes = generated.get("quotes")
        if not isinstance(quotes, list):
            raise ValueError("model output did not contain a quotes list")
        validated = []
        seen = set()
        for entry in quotes[:3]:
            if not isinstance(entry, dict):
                continue
            source_id = entry.get("source_id")
            quote = entry.get("text")
            source = by_id.get(source_id)
            if (
                not isinstance(quote, str)
                or len(quote.strip()) < 12
                or source is None
                or quote not in source
                or source_id in seen
            ):
                continue
            item = next(result for result in results if result["id"] == source_id)
            validated.append({
                "text": quote,
                "citations": [citation(item)],
                "groundedness": 100,
                "relevance": item["relevance"],
            })
            seen.add(source_id)
        if not validated:
            return evidence_suggestions(results), {
                "mode": "extractive-fallback",
                "notice": "Local model returned no verifiable exact excerpts; showing source excerpts instead.",
            }
        return validated, {"mode": "local-model", "notice": None}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
        return evidence_suggestions(results), {
            "mode": "extractive-fallback",
            "notice": f"Local model unavailable or invalid ({type(error).__name__}); showing source excerpts.",
        }


def jira_configuration():
    required = ("JIRA_BASE_URL", "JIRA_PROJECT_KEY", "JIRA_EMAIL", "JIRA_API_TOKEN")
    return all(os.environ.get(key, "").strip() for key in required)


def create_jira_issue(payload):
    if not jira_configuration():
        return 503, {"error": "Jira is not configured. Set JIRA_BASE_URL, JIRA_PROJECT_KEY, JIRA_EMAIL, and JIRA_API_TOKEN."}
    fields = ("overview", "component", "observations")
    if any(not isinstance(payload.get(key, ""), str) for key in fields):
        return 400, {"error": "Overview, component, and observations must be text."}
    overview = payload.get("overview", "").strip()
    component = payload.get("component", "").strip()
    observations = payload.get("observations", "").strip()
    query = " ".join((overview, component, observations))
    duplicate_tickets = [
        item for item in rank(query, limit=8)
        if item["kind"] == "ticket" and item["relevance"] >= MIN_RELEVANCE
    ]
    if duplicate_tickets:
        return 409, {
            "error": "A relevant previous Jira ticket exists. Review it before creating a duplicate.",
            "matches": [
                {"id": item["id"], "url": item["url"], "relevance": item["relevance"]}
                for item in duplicate_tickets[:3]
            ],
        }
    if not overview or not observations:
        return 400, {"error": "Overview and testing observations are required."}
    if max(map(len, (overview, component, observations))) > 5000:
        return 400, {"error": "Each field must be 5000 characters or fewer."}

    base_url = os.environ["JIRA_BASE_URL"].rstrip("/")
    project = os.environ["JIRA_PROJECT_KEY"]
    auth = base64.b64encode(
        f"{os.environ['JIRA_EMAIL']}:{os.environ['JIRA_API_TOKEN']}".encode()
    ).decode()
    description = (
        f"Overview: {overview}\n\nComponent: {component or 'Not provided'}\n\n"
        f"Testing observations: {observations}"
    )
    issue_data = {
        "fields": {
            "project": {"key": project},
            "summary": overview[:250],
            "description": {
                "type": "doc",
                "version": 1,
                "content": [{
                    "type": "paragraph",
                    "content": [{"type": "text", "text": description}],
                }],
            },
            "issuetype": {"name": os.environ.get("JIRA_ISSUE_TYPE", "Bug")},
        }
    }
    request = urllib.request.Request(
        f"{base_url}/rest/api/3/issue",
        data=json.dumps(issue_data).encode(),
        headers={
            "Authorization": f"Basic {auth}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            created = json.loads(response.read(64 * 1024).decode("utf-8"))
        key = created.get("key")
        if not key:
            return 502, {"error": "Jira response did not include an issue key."}
        return 201, {"key": key, "url": f"{base_url}/browse/{urllib.parse.quote(key)}"}
    except urllib.error.HTTPError as error:
        return 502, {"error": f"Jira rejected the request (HTTP {error.code}). Check project and issue-type configuration."}
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return 502, {"error": f"Could not reach Jira ({type(error).__name__}). No issue was confirmed created."}


class Handler(BaseHTTPRequestHandler):
    server_version = "SupportTriage/1.0"

    def send_json(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid Content-Length.")
        if length <= 0 or length > 100_000:
            raise ValueError("Request body must be between 1 and 100000 bytes.")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Request body must be valid JSON.") from error

    def do_GET(self):
        if self.path == "/":
            body = STATIC.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/status":
            self.send_json(200, {
                "jira_configured": jira_configuration(),
                "model_configured": bool(os.environ.get("OLLAMA_MODEL", "").strip()),
                "corpus_size": len(CORPUS),
                "min_relevance": MIN_RELEVANCE,
            })
        else:
            self.send_json(404, {"error": "Not found."})

    def do_POST(self):
        started = time.perf_counter()
        try:
            payload = self.read_json()
            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object.")
            if self.path == "/api/search":
                query = " ".join(str(payload.get(key, "")).strip() for key in (
                    "overview", "component", "observations"
                ))
                if not query.strip() or max(map(len, (
                    str(payload.get("overview", "")),
                    str(payload.get("component", "")),
                    str(payload.get("observations", "")),
                ))) > 5000:
                    self.send_json(400, {"error": "Enter query details (maximum 5000 characters per field)."})
                    return
                ranked = rank(query)
                matches = [item for item in ranked if item["relevance"] >= MIN_RELEVANCE]
                suggestions, model = local_model_quotes(query, matches)
                self.send_json(200, {
                    "matches": [
                        {
                            "id": item["id"],
                            "kind": item["kind"],
                            "title": item["title"],
                            "relevance": item["relevance"],
                            "citation": citation(item),
                            "resolution": item.get("resolution"),
                            "excerpt": item["text"] if item["kind"] == "manual" else None,
                        }
                        for item in matches[:6]
                    ],
                    "suggestions": suggestions,
                    "model": model,
                    "can_create": not any(item["kind"] == "ticket" for item in matches),
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                })
            elif self.path == "/api/jira":
                status, result = create_jira_issue(payload)
                self.send_json(status, result)
            else:
                self.send_json(404, {"error": "Not found."})
        except ValueError as error:
            self.send_json(400, {"error": str(error)})

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")


def main():
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    print(f"Support triage UI: http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
