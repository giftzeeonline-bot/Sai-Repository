import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import server


class RetrievalTests(unittest.TestCase):
    def test_drain_error_ranks_matching_ticket_and_manual_citation(self):
        results = server.rank("E21 drain filter water remains drum", limit=8)
        self.assertEqual("QA-1001", results[0]["id"])
        citations = [server.citation(item)["id"] for item in results]
        self.assertIn("SM-P001", citations)

    def test_suggestions_are_exactly_grounded_in_cited_record(self):
        results = server.rank("softener compartment retains water drawer", limit=8)
        matches = [item for item in results if item["relevance"] >= server.MIN_RELEVANCE]
        suggestions, model = server.local_model_quotes("softener water drawer", matches)
        self.assertEqual("extractive", model["mode"])
        for suggestion in suggestions:
            source_id = suggestion["citations"][0]["id"]
            source = next(item for item in matches if item["id"] == source_id)
            self.assertIn(suggestion["text"], source.get("resolution") or source["text"])
            self.assertEqual(100, suggestion["groundedness"])

    def test_local_model_timeout_uses_visible_extracts(self):
        results = server.rank("E21 drain filter", limit=4)
        with patch.dict("os.environ", {"OLLAMA_MODEL": "test-model"}), patch(
            "server.urllib.request.urlopen", side_effect=TimeoutError()
        ):
            suggestions, model = server.local_model_quotes("E21 drain filter", results)
        self.assertEqual("extractive-fallback", model["mode"])
        self.assertIn("TimeoutError", model["notice"])
        self.assertTrue(suggestions)


if __name__ == "__main__":
    unittest.main()
