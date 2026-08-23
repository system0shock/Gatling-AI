"""Behavioral tests for bounded GraphQL SDL extraction."""

from __future__ import annotations

import unittest
from unittest.mock import patch

if __package__:
    from . import contracts, graphql_sdl
else:
    import contracts
    import graphql_sdl


SHA256 = "3" * 64


def context(repo_id: str = "orders-schema", service_id: str | None = "orders") -> dict:
    return {
        "repo_id": repo_id,
        "snapshot_identity": "commit:abcdef0123456789",
        "service_id": service_id,
        "source": {
            "repo_id": repo_id,
            "revision": "abcdef0123456789",
            "path": "schema/orders.graphqls",
            "pointer": "#",
            "selection_reason": "graphql-sdl-signature",
            "sha256": SHA256,
        },
    }


class GraphqlSdlExtractorTests(unittest.TestCase):
    def test_standard_roots_emit_one_interface_per_field_with_deterministic_types(self) -> None:
        """Omitting a root field or changing argument/type normalization must fail."""
        text = """
            type Query { document(id: ID!): Document }
            type Mutation { createDocument(input: CreateDocument!, id: ID): Document! }
            type Subscription { documentCreated: DocumentCreated! }
            type Document { id: ID! }
        """

        result = graphql_sdl.extract_graphql_sdl(text, context()).to_dict()

        self.assertEqual([candidate["canonical_key"] for candidate in result["candidates"]], [
            "graphql:orders:Mutation:createDocument",
            "graphql:orders:Query:document",
            "graphql:orders:Subscription:documentCreated",
        ])
        mutation = result["candidates"][0]
        self.assertEqual(mutation["attributes"], {
            "argument_names": ["id", "input"],
            "argument_types": ["ID", "CreateDocument!"],
            "arguments": ["id: ID", "input: CreateDocument!"],
            "field": "createDocument",
            "operation": "Mutation.createDocument",
            "protocol": "GraphQL",
            "return_type": "Document!",
            "root_operation": "Mutation",
            "root_type": "Mutation",
        })
        self.assertEqual(mutation["source"], context()["source"] | {"pointer": "#type/Mutation/field/createDocument"})
        self.assertNotIn("size_bytes", mutation["source"])
        contracts.validate_artifact(result, "methodology-extractor-result.schema.json")

    def test_schema_mapping_and_object_extensions_are_roots_without_extra_objects(self) -> None:
        """Ignoring schema root mapping/extensions or scanning ordinary objects must fail."""
        text = """
            schema { query: RootRead mutation: RootWrite }
            extend schema { subscription: RootEvents }
            type RootRead { zeta: String }
            extend type RootRead { alpha(id: [ID!]!): String! }
            type RootWrite { create: Boolean! }
            type RootEvents { changed: String }
            type Query { mustNotBeRoot: String }
            type Ordinary { ignored: String }
        """

        result = graphql_sdl.extract_graphql_sdl(text, context()).to_dict()

        self.assertEqual([candidate["canonical_key"] for candidate in result["candidates"]], [
            "graphql:orders:Mutation:create",
            "graphql:orders:Query:alpha",
            "graphql:orders:Query:zeta",
            "graphql:orders:Subscription:changed",
        ])
        alpha = result["candidates"][1]
        self.assertEqual(alpha["attributes"]["root_operation"], "Query")
        self.assertEqual(alpha["attributes"]["root_type"], "RootRead")
        self.assertEqual(alpha["attributes"]["argument_types"], ["[ID!]!"])
        self.assertFalse(any("mustNotBeRoot" in candidate["canonical_key"] for candidate in result["candidates"]))

    def test_invalid_sdl_and_invalid_text_are_structured_without_introspection(self) -> None:
        """Parser failures must become closed errors and never execute a GraphQL server call."""
        with patch("graphql.graphql_sync", side_effect=AssertionError("introspection")):
            invalid = graphql_sdl.extract_graphql_sdl("type Query { broken(: String }", context()).to_dict()

        self.assertEqual(invalid["candidates"], [])
        self.assertEqual(invalid["warnings"], [])
        self.assertEqual(invalid["errors"][0]["code"], "invalid-graphql-sdl")
        self.assertNotIn("Traceback", invalid["errors"][0]["message"])
        contracts.validate_artifact(invalid, "methodology-extractor-result.schema.json")

        non_text = graphql_sdl.extract_graphql_sdl({"query": "type Query"}, context()).to_dict()
        self.assertEqual(non_text["errors"][0]["code"], "invalid-graphql-sdl")

    def test_duplicate_extension_field_warns_but_keeps_valid_siblings_deterministically(self) -> None:
        """A malformed duplicate field must not erase a valid sibling or duplicate a key."""
        text = """
            type Query { document: String health: String }
            extend type Query { document: Int }
        """

        first = graphql_sdl.extract_graphql_sdl(text, context()).to_dict()
        second = graphql_sdl.extract_graphql_sdl(text, context()).to_dict()

        self.assertEqual(first, second)
        self.assertEqual([candidate["canonical_key"] for candidate in first["candidates"]], [
            "graphql:orders:Query:document",
            "graphql:orders:Query:health",
        ])
        self.assertEqual([warning["code"] for warning in first["warnings"]], ["duplicate-root-field"])
        contracts.validate_artifact(first, "methodology-extractor-result.schema.json")


if __name__ == "__main__":
    unittest.main()
