"""Behavioral tests for the opt-in, line-oriented Java marker extractor."""

from __future__ import annotations

import hashlib
import unittest

if __package__:
    from . import contracts, java_markers, locator
    from .models import DiscoveryBudget
else:
    import contracts
    import java_markers
    import locator
    from models import DiscoveryBudget


JAVA = """\
@RestController
@RequestMapping("/documents")
class DocumentController {
  @PostMapping("/{id}")
  void create() {}
  @KafkaListener(topics = "document.created")
  void consume() {}
  @QueryMapping(name = "document")
  Object document() { return null; }
  @MutationMapping
  Object updateDocument() { return null; }
  @GetMapping(path = BASE_PATH)
  void dynamicPath() {}
  @KafkaListener(topics = "${topic.name}")
  void dynamicTopic() {}
}
"""


def context(text: str = JAVA) -> dict:
    return {
        "repo_id": "orders-backend",
        "snapshot_identity": "commit:abcdef0123456789",
        "service_id": "orders",
        "source": {
            "repo_id": "orders-backend",
            "revision": "abcdef0123456789",
            "path": "src/DocumentController.java",
            "pointer": "#",
            "selection_reason": "java-framework-marker",
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
        },
    }


class JavaMarkerExtractorTests(unittest.TestCase):
    def test_class_paths_do_not_leak_and_literal_arrays_expand_deterministically(self) -> None:
        text = """\
@RequestMapping(path = {"/one", "/alias"})
class First {
  @RequestMapping(path = {"/a", "/b"}, method = {RequestMethod.GET, RequestMethod.POST})
  void mapped() {}
  @KafkaListener(id = "not-a-topic", topics = {"right.one", "right.two"})
  void listen() {}
}
@RequestMapping("/two")
class Second {
  @GetMapping("/c")
  void second() {}
}
class Third {
  @GetMapping("/plain")
  void third() {}
}
"""

        result = java_markers.extract_java_markers(text, context(text), 500).to_dict()

        http_paths = {
            (item["attributes"]["method"], item["attributes"]["path"])
            for item in result["candidates"]
            if item["attributes"].get("protocol") == "HTTP"
        }
        self.assertEqual(
            http_paths,
            {
                (method, f"{prefix}/{suffix}")
                for method in ("GET", "POST")
                for prefix in ("/one", "/alias")
                for suffix in ("a", "b")
            }
            | {("GET", "/two/c"), ("GET", "/plain")},
        )
        topics = {
            item["attributes"]["topic"]
            for item in result["candidates"]
            if item["attributes"].get("protocol") == "Kafka"
        }
        self.assertEqual(topics, {"right.one", "right.two"})
        self.assertNotIn("not-a-topic", topics)

    def test_fixed_annotations_emit_candidate_paths_topics_and_graphql_fields(self) -> None:
        result = java_markers.extract_java_markers(JAVA, context(), 500).to_dict()

        contracts.validate_artifact(result, "methodology-extractor-result.schema.json")
        self.assertTrue(all(item["confidence"] == "candidate" for item in result["candidates"]))
        http = next(item for item in result["candidates"] if item["attributes"].get("protocol") == "HTTP")
        kafka = next(item for item in result["candidates"] if item["attributes"].get("protocol") == "Kafka")
        graphql = [item for item in result["candidates"] if item["attributes"].get("protocol") == "GraphQL"]
        self.assertEqual((http["attributes"]["method"], http["attributes"]["path"]), ("POST", "/documents/{id}"))
        self.assertEqual(kafka["attributes"]["topic"], "document.created")
        self.assertEqual({item["attributes"]["field"] for item in graphql}, {"document", "updateDocument"})
        self.assertEqual({item["attributes"]["root_operation"] for item in graphql}, {"Query", "Mutation"})
        self.assertTrue(all(item["source"]["pointer"].startswith("#L") for item in result["candidates"]))
        self.assertIn("dynamic-java-annotation", {warning["code"] for warning in result["warnings"]})
        self.assertNotIn("BASE_PATH", str(result["candidates"]))
        self.assertNotIn("topic.name", str(result["candidates"]))

    def test_candidate_501_is_not_emitted_and_reports_budget_exhaustion(self) -> None:
        text = "\n".join(f'@KafkaListener(topics = "topic.{number}")' for number in range(501))

        result = java_markers.extract_java_markers(text, context(text), 500).to_dict()

        self.assertEqual(len(result["candidates"]), 500)
        self.assertNotIn("topic.500", {item["attributes"]["topic"] for item in result["candidates"]})
        self.assertEqual(result["warnings"][-1]["code"], "source-marker-candidate-limit")
        self.assertTrue(result["limit_reached"])

    def test_dynamic_class_path_and_block_comment_annotations_invent_no_interfaces(self) -> None:
        text = """\
@RequestMapping(path = BASE_PATH)
class DynamicController {
  @GetMapping("/must-not-lose-prefix")
  void hiddenByDynamicPrefix() {}
}
/*
  @PostMapping("/comment-only")
*/
class PlainController {}
"""

        result = java_markers.extract_java_markers(text, context(text), 500).to_dict()

        self.assertEqual(result["candidates"], [])
        self.assertEqual(
            {warning["code"] for warning in result["warnings"]},
            {"dynamic-java-annotation"},
        )

    def test_remaining_budget_must_be_a_nonnegative_integer(self) -> None:
        for invalid in (-1, 1.5, True):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "remaining_candidate_budget"):
                    java_markers.extract_java_markers(JAVA, context(), invalid)

    def test_disabled_locator_never_selects_java_for_extraction(self) -> None:
        class View:
            source_mode = "git-object"
            snapshot_identity = "commit:abcdef0123456789"
            revision = "abcdef0123456789"

            def list_paths(self) -> tuple[str, ...]:
                return ("src/DocumentController.java",)

            def read_bytes(self, path: str, max_bytes: int) -> bytes:
                raise AssertionError("disabled source marker scan must not read Java")

            def verify_run_guard(self) -> None:
                return None

        repository = type("Repository", (), {"module_id": "orders-backend", "inspect": (), "exclude": ()})()
        budget = DiscoveryBudget(1024, 0, 1024, 500)

        index = locator.locate_sources(View(), repository, budget, source_markers_enabled=False)

        self.assertEqual(index["selected_files"], [])
        self.assertEqual(index["counters"]["source_marker_candidates"], 0)


if __name__ == "__main__":
    unittest.main()
