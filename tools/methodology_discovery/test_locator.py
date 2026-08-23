#!/usr/bin/env python3
"""Hard-budget and signature tests for deterministic source location."""

from __future__ import annotations

import hashlib
import unittest
from dataclasses import dataclass

if __package__:
    from . import contracts, locator
    from .models import DiscoveryBudget
    from .source_views import DiscoveryError, normalize_source_path
else:
    import contracts
    import locator
    from models import DiscoveryBudget
    from source_views import DiscoveryError, normalize_source_path


MIB = 1024 * 1024


@dataclass(frozen=True)
class Repository:
    module_id: str = "orders"
    inspect: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()


class MemorySourceView:
    source_mode = "git-object"
    snapshot_identity = "commit:0123456789abcdef"
    revision = "0123456789abcdef"

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = dict(files)
        self.read_paths: list[str] = []
        self.guard_checks = 0

    def list_paths(self) -> tuple[str, ...]:
        return tuple(sorted(self.files))

    def read_bytes(self, path: str, max_bytes: int) -> bytes:
        normalized = normalize_source_path(path)
        self.read_paths.append(normalized)
        content = self.files[normalized]
        if len(content) > max_bytes:
            raise DiscoveryError(
                "source-file-too-large",
                f"source is {len(content)} bytes; hard limit is {max_bytes}",
                path=normalized,
            )
        return content

    def read_text(self, path: str, max_bytes: int) -> str:
        content = self.read_bytes(path, max_bytes)
        if b"\x00" in content:
            raise DiscoveryError("source-not-utf8-text", "NUL byte", path=path)
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DiscoveryError("source-not-utf8-text", "invalid UTF-8", path=path) from exc

    def verify_run_guard(self) -> None:
        self.guard_checks += 1


def selected_paths(index: dict) -> list[str]:
    return [record["path"] for record in index["selected_files"]]


class LocatorTests(unittest.TestCase):
    def test_default_budget_is_the_exact_approved_mvp_boundary(self) -> None:
        """Changing any default must change a visible recorded run option."""
        self.assertEqual(
            locator.DEFAULT_BUDGET,
            DiscoveryBudget(
                structured_file_bytes=5 * MIB,
                document_count=20,
                document_file_bytes=1 * MIB,
                source_marker_candidates=500,
            ),
        )

    def test_exclusions_precede_signature_read_and_roles_never_prove_a_source(self) -> None:
        """A role or filename cannot bypass exclusions or missing content evidence."""
        files = {
            "api/a.yaml": b"openapi: 3.0.0\npaths: {}\n",
            "api/z.yaml": b"swagger: '2.0'\npaths: {}\n",
            "arbitrary.txt": b"documentation role is not proof",
            "configured/contract.yaml": b"openapi: 3.0.0\npaths: {}\n",
            "node_modules/contract.yaml": b"openapi: 3.0.0\npaths: {}\n",
            "plain.yaml": b"title: OpenAPI in a misleading filename\n",
        }
        view = MemorySourceView(files)
        repository = Repository(
            inspect=("api/z.yaml", "arbitrary.txt"),
            exclude=("configured",),
            roles=("documentation", "contracts"),
        )

        index = locator.locate_sources(
            view, repository, locator.DEFAULT_BUDGET, source_markers_enabled=False
        )

        self.assertEqual(selected_paths(index), ["api/z.yaml", "api/a.yaml"])
        self.assertNotIn("configured/contract.yaml", view.read_paths)
        self.assertNotIn("node_modules/contract.yaml", view.read_paths)
        self.assertNotIn("arbitrary.txt", selected_paths(index))
        self.assertIn(
            {"path": "plain.yaml", "reason": "unrecognized-signature"},
            index["skipped_files"],
        )
        self.assertEqual(view.guard_checks, 1)
        contracts.validate_artifact(index, "methodology-discovery-index.schema.json")

    def test_contracts_documents_configuration_and_markers_have_stable_layer_order(self) -> None:
        """Reversing input enumeration must not change category or path ordering."""
        files = {
            "src/Z.java": b"class Z { @KafkaListener(topics = \"created\") void x() {} }",
            "application.yml": b"spring:\n  application:\n    name: orders\n",
            "docs/architecture/system.md": b"# Architecture\nExplicit flow.",
            "README.md": b"# Orders\nEndpoints are documented.",
            "api/async.yaml": b"asyncapi: 2.6.0\nchannels: {}\n",
            "api/openapi.json": b'{"openapi":"3.0.0","paths":{}}',
        }
        view = MemorySourceView(dict(reversed(list(files.items()))))

        index = locator.locate_sources(
            view, Repository(), locator.DEFAULT_BUDGET, source_markers_enabled=True
        )

        self.assertEqual(
            selected_paths(index),
            [
                "api/async.yaml",
                "api/openapi.json",
                "README.md",
                "docs/architecture/system.md",
                "application.yml",
                "src/Z.java",
            ],
        )
        self.assertEqual(
            [record["selection_reason"] for record in index["selected_files"]],
            [
                "asyncapi-signature",
                "openapi-signature",
                "readme-document",
                "architecture-document",
                "spring-configuration-signature",
                "java-framework-marker",
            ],
        )

    def test_twenty_document_limit_is_visible_and_never_silently_expands(self) -> None:
        """Selecting document 21 must fail even though all documents are high-signal."""
        files = {
            f"docs/architecture/{number:02d}.md": f"# Doc {number}\n".encode()
            for number in range(21)
        }
        view = MemorySourceView(files)

        index = locator.locate_sources(
            view, Repository(), locator.DEFAULT_BUDGET, source_markers_enabled=False
        )

        self.assertEqual(len(index["selected_files"]), 20)
        self.assertNotIn("docs/architecture/20.md", selected_paths(index))
        self.assertIn(
            {"path": "docs/architecture/20.md", "reason": "document-count-limit"},
            index["skipped_files"],
        )
        self.assertTrue(index["limit_reached"])
        self.assertIn("document-count-limit", [item["code"] for item in index["warnings"]])
        self.assertEqual(index["counters"]["documents_selected"], 20)

    def test_source_markers_are_opt_in_signature_selected_and_capped(self) -> None:
        """A disabled marker layer or an annotation-free Java file must select nothing."""
        files = {
            "src/A.java": b"class A { @GetMapping(\"/a\") void a() {} }",
            "src/B.java": b"class B { @KafkaListener(topics = \"b\") void b() {} }",
            "src/C.java": b"class C {}",
        }
        disabled_view = MemorySourceView(files)
        disabled = locator.locate_sources(
            disabled_view, Repository(), locator.DEFAULT_BUDGET, source_markers_enabled=False
        )
        budget = DiscoveryBudget(5 * MIB, 20, MIB, 1)
        enabled_view = MemorySourceView(files)
        enabled = locator.locate_sources(
            enabled_view, Repository(), budget, source_markers_enabled=True
        )

        self.assertEqual(selected_paths(disabled), [])
        self.assertFalse(any(path.endswith(".java") for path in disabled_view.read_paths))
        self.assertEqual(selected_paths(enabled), ["src/A.java"])
        self.assertIn(
            {"path": "src/B.java", "reason": "source-marker-candidate-limit"},
            enabled["skipped_files"],
        )
        self.assertIn(
            {"path": "src/C.java", "reason": "unrecognized-signature"},
            enabled["skipped_files"],
        )
        self.assertTrue(enabled["limit_reached"])

    def test_marker_overflow_inside_one_selected_file_is_visible(self) -> None:
        """A file with two markers must not hide a one-candidate budget overflow."""
        view = MemorySourceView({
            "src/A.java": b'class A { @GetMapping("/a") void a() {} }',
            "src/B.java": (
                b'class A { @GetMapping("/a") void a() {} '
                b'@PostMapping("/b") void b() {} }'
            ),
        })
        budget = DiscoveryBudget(5 * MIB, 20, MIB, 2)

        index = locator.locate_sources(
            view, Repository(), budget, source_markers_enabled=True
        )

        self.assertEqual(selected_paths(index), ["src/A.java", "src/B.java"])
        self.assertEqual(index["counters"]["source_marker_candidates"], 2)
        self.assertTrue(index["limit_reached"])
        self.assertIn(
            "source-marker-candidate-limit", [item["code"] for item in index["warnings"]]
        )

    def test_structured_contract_under_document_path_is_selected_once_as_contract(self) -> None:
        """Path-based document priority must not duplicate stronger content evidence."""
        view = MemorySourceView({
            "docs/architecture/openapi.yaml": b"openapi: 3.0.0\npaths: {}\n",
        })

        index = locator.locate_sources(
            view, Repository(), locator.DEFAULT_BUDGET, source_markers_enabled=False
        )

        self.assertEqual(selected_paths(index), ["docs/architecture/openapi.yaml"])
        self.assertEqual(index["selected_files"][0]["selection_reason"], "openapi-signature")
        self.assertEqual(view.read_paths, ["docs/architecture/openapi.yaml"])

    def test_structured_selection_requires_top_level_content_signatures(self) -> None:
        """Extension-only parsing must not misclassify contracts, GraphQL, or deployment."""
        files = {
            "Chart.yaml": b"apiVersion: v2\nname: orders\nversion: 1.0.0\n",
            "api/schema.graphqls": b"type Query { order: Order }\ntype Order { id: ID! }\n",
            "api/not-schema.graphql": b"query FindOrder { order { id } }\n",
            "build.gradle.kts": b"plugins { java }\nrootProject.name = \"orders\"\n",
            "compose.yaml": b"services:\n  orders:\n    image: orders:latest\n",
            "deployment.yaml": b"apiVersion: apps/v1\nkind: Deployment\nmetadata: {name: orders}\n",
            "fake-openapi.yaml": b"info:\n  title: openapi\n",
            "pom.xml": b"<project><artifactId>orders</artifactId></project>\n",
        }
        view = MemorySourceView(files)

        index = locator.locate_sources(
            view, Repository(), locator.DEFAULT_BUDGET, source_markers_enabled=False
        )

        self.assertEqual(
            [(item["path"], item["selection_reason"]) for item in index["selected_files"]],
            [
                ("api/schema.graphqls", "graphql-sdl-signature"),
                ("Chart.yaml", "helm-chart-signature"),
                ("build.gradle.kts", "gradle-build-signature"),
                ("compose.yaml", "docker-compose-signature"),
                ("deployment.yaml", "kubernetes-signature"),
                ("pom.xml", "maven-build-signature"),
            ],
        )
        skipped = {item["path"]: item["reason"] for item in index["skipped_files"]}
        self.assertEqual(skipped["api/not-schema.graphql"], "unrecognized-signature")
        self.assertEqual(skipped["fake-openapi.yaml"], "unrecognized-signature")

    def test_explicit_utf8_document_crosses_only_the_bounded_user_boundary(self) -> None:
        """Removing the explicit reason or normalized path check must fail this boundary."""
        files = {"notes/system.txt": b"Explicitly described interface and flow."}
        view = MemorySourceView(files)

        index = locator.locate_sources(
            view,
            Repository(),
            locator.DEFAULT_BUDGET,
            source_markers_enabled=False,
            user_documents=("notes/system.txt",),
        )

        self.assertEqual(selected_paths(index), ["notes/system.txt"])
        self.assertEqual(
            index["selected_files"][0]["selection_reason"], "user-supplied-document"
        )
        with self.assertRaisesRegex(DiscoveryError, "invalid-source-path"):
            locator.locate_sources(
                view,
                Repository(),
                locator.DEFAULT_BUDGET,
                source_markers_enabled=False,
                user_documents=("../outside.md",),
            )

    def test_explicit_binary_oversized_and_twenty_first_documents_are_rejected(self) -> None:
        """Explicit selection is not authority to exceed text or document budgets."""
        binary_view = MemorySourceView({"notes.bin": b"\xff\x00"})
        with self.assertRaisesRegex(DiscoveryError, "source-not-utf8-text"):
            locator.locate_sources(
                binary_view,
                Repository(),
                locator.DEFAULT_BUDGET,
                source_markers_enabled=False,
                user_documents=("notes.bin",),
            )

        oversized_view = MemorySourceView({"notes.txt": b"x" * (MIB + 1)})
        oversized = locator.locate_sources(
            oversized_view,
            Repository(),
            locator.DEFAULT_BUDGET,
            source_markers_enabled=False,
            user_documents=("notes.txt",),
        )
        self.assertEqual(selected_paths(oversized), [])
        self.assertEqual(oversized["skipped_files"][0]["reason"], "document-file-byte-limit")
        self.assertTrue(oversized["limit_reached"])

        files = {f"notes/{number:02d}.txt": b"explicit" for number in range(21)}
        twenty_one = locator.locate_sources(
            MemorySourceView(files),
            Repository(),
            locator.DEFAULT_BUDGET,
            source_markers_enabled=False,
            user_documents=tuple(sorted(files)),
        )
        self.assertEqual(len(twenty_one["selected_files"]), 20)
        self.assertEqual(twenty_one["skipped_files"][-1], {
            "path": "notes/20.txt", "reason": "document-count-limit"
        })

    def test_every_content_read_is_recorded_as_selected_or_skipped_with_hashes_on_selection(self) -> None:
        """A locator read must never disappear from the auditable discovery index."""
        view = MemorySourceView({
            "api/openapi.yaml": b"openapi: 3.0.0\npaths: {}\n",
            "fake.yaml": b"name: not-a-contract\n",
            "README.md": b"# System\n",
        })

        index = locator.locate_sources(
            view, Repository(), locator.DEFAULT_BUDGET, source_markers_enabled=False
        )

        recorded = {
            item["path"] for item in index["selected_files"]
        } | {item["path"] for item in index["skipped_files"]}
        self.assertEqual(set(view.read_paths), recorded)
        by_path = {item["path"]: item for item in index["selected_files"]}
        self.assertEqual(
            by_path["api/openapi.yaml"]["sha256"],
            hashlib.sha256(view.files["api/openapi.yaml"]).hexdigest(),
        )
        self.assertEqual(
            by_path["api/openapi.yaml"]["size_bytes"],
            len(view.files["api/openapi.yaml"]),
        )
        self.assertEqual(
            by_path["README.md"]["size_bytes"], len(view.files["README.md"])
        )
        self.assertEqual(index["counters"]["selected_files"], 2)
        self.assertEqual(index["counters"]["skipped_files"], 1)
        contracts.validate_artifact(index, "methodology-discovery-index.schema.json")


if __name__ == "__main__":
    unittest.main()
