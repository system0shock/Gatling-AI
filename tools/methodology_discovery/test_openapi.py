"""Behavioral tests for bounded OpenAPI and Swagger extraction."""

from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import patch

if __package__:
    from . import contracts, openapi
else:
    import contracts
    import openapi


SHA256 = "1" * 64


def context(repo_id: str = "orders-contracts", service_id: str | None = "orders") -> dict:
    return {
        "repo_id": repo_id,
        "snapshot_identity": "commit:0123456789abcdef",
        "service_id": service_id,
        "source": {
            "repo_id": repo_id,
            "revision": "0123456789abcdef",
            "path": "api/openapi.yaml",
            "pointer": "#",
            "selection_reason": "openapi-signature",
            "sha256": SHA256,
        },
    }


class OpenApiExtractorTests(unittest.TestCase):
    def test_excessively_nested_yaml_text_is_a_structured_parse_error(self) -> None:
        """Safe YAML recursion must not escape the bounded text parser."""
        nested_yaml = "[" * 2_000 + "0" + "]" * 2_000

        result = openapi.extract_openapi(nested_yaml, context()).to_dict()

        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["errors"][0]["code"], "invalid-openapi-document")
        self.assertNotIn("Traceback", result["errors"][0]["message"])

    def test_openapi_three_servers_use_operation_path_root_precedence(self) -> None:
        """Path-level servers must override root and yield to operation-level servers."""
        document = {
            "openapi": "3.0.3",
            "info": {"title": "Orders"},
            "servers": [{"url": "https://root.example.test"}],
            "paths": {
                "/root": {"get": {"responses": {"200": {}}}},
                "/path": {
                    "servers": [{"url": "https://path.example.test"}],
                    "get": {"responses": {"200": {}}},
                },
                "/operation": {
                    "servers": [{"url": "https://path.example.test"}],
                    "get": {
                        "servers": [{"url": "https://operation.example.test"}],
                        "responses": {"200": {}},
                    },
                },
                "/empty-operation": {
                    "servers": [{"url": "https://path.example.test"}],
                    "get": {"servers": [], "responses": {"200": {}}},
                },
            },
        }

        result = openapi.extract_openapi(document, context()).to_dict()
        attributes_by_path = {
            candidate["attributes"]["path"]: candidate["attributes"]
            for candidate in result["candidates"]
        }

        self.assertEqual(attributes_by_path["/root"]["servers"], ["https://root.example.test"])
        self.assertEqual(attributes_by_path["/path"]["servers"], ["https://path.example.test"])
        self.assertEqual(attributes_by_path["/operation"]["servers"], ["https://operation.example.test"])
        self.assertNotIn("servers", attributes_by_path["/empty-operation"])

    def test_normalized_openapi_key_collision_is_visible_and_deterministic(self) -> None:
        """Two raw paths collapsing to one key must not remain silently ambiguous."""
        path_items = [
            ("/documents//{ id }/", {"post": {"responses": {"201": {}}}}),
            ("/documents/{id}", {"post": {"responses": {"202": {}}}}),
        ]
        document = {
            "openapi": "3.0.3",
            "info": {"title": "Orders"},
            "paths": dict(path_items),
        }
        reversed_document = document | {"paths": dict(reversed(path_items))}

        first = openapi.extract_openapi(document, context()).to_dict()
        second = openapi.extract_openapi(reversed_document, context()).to_dict()

        self.assertEqual(first, second)
        self.assertEqual(len(first["candidates"]), 2)
        self.assertEqual(
            {candidate["canonical_key"] for candidate in first["candidates"]},
            {"http:orders:POST:/documents/{id}"},
        )
        self.assertEqual([warning["code"] for warning in first["warnings"]], ["canonical-key-collision"])
        self.assertIn("http:orders:POST:/documents/{id}", first["warnings"][0]["message"])

    def test_case_insensitive_method_preserves_raw_rfc6901_pointer_token(self) -> None:
        """An accepted mixed-case method pointer must exist in the supplied mapping."""
        document = {
            "openapi": "3.0.3",
            "info": {"title": "Orders"},
            "paths": {"/mixed": {"PoSt": {"responses": {"201": {}}}}},
        }

        result = openapi.extract_openapi(document, context()).to_dict()

        self.assertEqual(result["candidates"][0]["attributes"]["method"], "POST")
        self.assertEqual(result["candidates"][0]["source"]["pointer"], "#/paths/~1mixed/PoSt")

    def test_explicit_invalid_contract_service_id_is_unknown_not_title_metadata(self) -> None:
        """Invalid explicit identity evidence must not silently fall through to title."""
        document = {
            "openapi": "3.0.3",
            "info": {"title": "Orders Metadata", "x-service-id": "Not A Valid Id"},
            "paths": {"/documents": {"get": {"responses": {"200": {}}}}},
        }

        result = openapi.extract_openapi(document, context(service_id="orders")).to_dict()

        candidate = result["candidates"][0]
        self.assertEqual(candidate["service_identity"], {"value": "repo-orders-contracts", "basis": "unknown"})
        self.assertEqual(candidate["canonical_key"], "http:repo-orders-contracts:GET:/documents")
        self.assertEqual([warning["code"] for warning in result["warnings"]], ["invalid-service-identity"])
        self.assertIn("Not A Valid Id", result["warnings"][0]["message"])

    def test_caller_supplied_json_and_safe_yaml_text_are_parsed_in_memory(self) -> None:
        """Rejecting valid bounded text or constructing unsafe YAML objects must fail."""
        texts = (
            '{"openapi":"3.0.3","info":{"title":"Orders"},"paths":{"/json":{"get":{"responses":{"200":{}}}}}}',
            "openapi: 3.0.3\ninfo:\n  title: Orders\npaths:\n  /yaml:\n    post:\n      responses:\n        '201': {}\n",
        )
        expected = ("http:orders:GET:/json", "http:orders:POST:/yaml")
        for text, canonical_key in zip(texts, expected, strict=True):
            with self.subTest(canonical_key=canonical_key):
                result = openapi.extract_openapi(text, context()).to_dict()
                self.assertEqual(result["errors"], [])
                self.assertEqual(result["candidates"][0]["canonical_key"], canonical_key)

        for unsafe in ("!!python/object/apply:builtins.str [unsafe]", "openapi: ["):
            with self.subTest(unsafe=unsafe):
                result = openapi.extract_openapi(unsafe, context()).to_dict()
                self.assertEqual(result["candidates"], [])
                self.assertEqual(result["errors"][0]["code"], "invalid-openapi-document")

    def test_openapi_three_normalizes_operation_and_keeps_declared_metadata(self) -> None:
        """Dropping an operation attribute or path normalization must fail this contract."""
        document = {
            "openapi": "3.1.0",
            "info": {"title": "Orders API", "x-service-id": "orders"},
            "servers": [{"url": "https://api.example.test/v1"}],
            "paths": {
                "documents//{ id }/": {
                    "post": {
                        "operationId": "createDocument",
                        "summary": "Create a document",
                        "tags": ["write", "documents", "write"],
                        "responses": {"400": {}, "201": {}, "default": {}},
                    }
                }
            },
        }
        original = deepcopy(document)

        result = openapi.extract_openapi(document, context()).to_dict()

        self.assertEqual(document, original)
        self.assertEqual(result["extractor_id"], "openapi")
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["candidates"]), 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["canonical_key"], "http:orders:POST:/documents/{id}")
        self.assertEqual(candidate["display_name"], "POST /documents/{id}")
        self.assertEqual(candidate["service_identity"], {"value": "orders", "basis": "contract"})
        self.assertEqual(
            candidate["attributes"],
            {
                "method": "POST",
                "operation": "POST /documents/{id}",
                "operation_id": "createDocument",
                "path": "/documents/{id}",
                "protocol": "HTTP",
                "response_codes": ["201", "400", "default"],
                "servers": ["https://api.example.test/v1"],
                "summary": "Create a document",
                "tags": ["documents", "write"],
            },
        )
        self.assertEqual(
            candidate["source"],
            context()["source"] | {"pointer": "#/paths/documents~1~1{ id }~1/post"},
        )
        self.assertNotIn("size_bytes", candidate["source"])
        contracts.validate_artifact(result, "methodology-extractor-result.schema.json")

    def test_all_standard_http_operation_keys_survive_malformed_siblings_deterministically(self) -> None:
        """Omitting any standard method or aborting on one bad sibling must fail."""
        methods = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
        document = {
            "openapi": "3.0.3",
            "info": {"title": "Orders"},
            "paths": {
                "/z": {method: {"responses": {"204": {}}} for method in reversed(methods)},
                "/bad": {"get": "not-an-operation", "post": {"responses": {"202": {}}}},
            },
        }

        first = openapi.extract_openapi(document, context(service_id=None)).to_dict()
        second = openapi.extract_openapi(deepcopy(document), context(service_id=None)).to_dict()

        self.assertEqual(first, second)
        self.assertEqual(len(first["candidates"]), 9)
        self.assertEqual(
            {item["attributes"]["method"] for item in first["candidates"] if item["attributes"]["path"] == "/z"},
            {method.upper() for method in methods},
        )
        self.assertEqual([item["canonical_key"] for item in first["candidates"]], sorted(item["canonical_key"] for item in first["candidates"]))
        self.assertEqual([warning["code"] for warning in first["warnings"]], ["malformed-operation"])
        contracts.validate_artifact(first, "methodology-extractor-result.schema.json")

    def test_swagger_two_preserves_base_path_and_service_identity_rules(self) -> None:
        """Swagger metadata must not become environment evidence or merge unknown repos."""
        document = {
            "swagger": "2.0",
            "info": {"title": "Billing Gateway", "x-service-id": "billing"},
            "basePath": "/v2",
            "host": "billing.example.test",
            "schemes": ["https"],
            "paths": {"documents": {"get": {"responses": {"200": {}}}}},
        }

        conflict = openapi.extract_openapi(document, context(service_id="orders")).to_dict()
        self.assertEqual(conflict["candidates"][0]["canonical_key"], "http:repo-orders-contracts:GET:/documents")
        self.assertEqual(conflict["candidates"][0]["service_identity"], {"value": "repo-orders-contracts", "basis": "unknown"})
        self.assertEqual(conflict["candidates"][0]["attributes"]["base_path"], "/v2")
        self.assertEqual(conflict["candidates"][0]["attributes"]["host"], "billing.example.test")
        self.assertEqual(conflict["candidates"][0]["attributes"]["schemes"], ["https"])
        self.assertEqual(conflict["warnings"][0]["code"], "service-identity-conflict")
        self.assertIn("orders", conflict["warnings"][0]["message"])
        self.assertIn("billing", conflict["warnings"][0]["message"])

        contract_only = openapi.extract_openapi(document, context(service_id=None)).to_dict()
        self.assertEqual(contract_only["candidates"][0]["service_identity"], {"value": "billing", "basis": "contract"})

        metadata_document = deepcopy(document)
        del metadata_document["info"]["x-service-id"]
        metadata = openapi.extract_openapi(metadata_document, context(service_id=None)).to_dict()
        self.assertEqual(metadata["candidates"][0]["service_identity"], {"value": "billing-gateway", "basis": "metadata"})

        unknown_document = deepcopy(metadata_document)
        unknown_document["info"]["title"] = "   "
        other = context(repo_id="other-contracts", service_id=None)
        other["source"]["path"] = "openapi.json"
        unknown = openapi.extract_openapi(unknown_document, other).to_dict()
        self.assertEqual(unknown["candidates"][0]["canonical_key"], "http:repo-other-contracts:GET:/documents")
        self.assertEqual(unknown["candidates"][0]["service_identity"]["basis"], "unknown")

    def test_remote_refs_are_never_fetched_and_invalid_top_level_is_structured(self) -> None:
        """A reference or invalid document must not cause I/O, traceback, or an exception."""
        document = {
            "openapi": "3.0.3",
            "info": {"title": "Orders"},
            "paths": {
                "/remote": {"$ref": "https://example.invalid/path-item.yaml"},
                "/local": {"get": {"responses": {"200": {"$ref": "https://example.invalid/response.yaml"}}}},
            },
        }
        with patch("urllib.request.urlopen", side_effect=AssertionError("network fetch")):
            result = openapi.extract_openapi(document, context()).to_dict()

        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual([warning["code"] for warning in result["warnings"]], ["reference-not-resolved"])
        invalid = openapi.extract_openapi(["not", "a", "mapping"], context()).to_dict()
        self.assertEqual(invalid["candidates"], [])
        self.assertEqual(invalid["warnings"], [])
        self.assertEqual(invalid["errors"][0]["code"], "invalid-openapi-document")
        self.assertNotIn("Traceback", invalid["errors"][0]["message"])
        contracts.validate_artifact(invalid, "methodology-extractor-result.schema.json")

        for unsupported in (
            {"openapi": "2.0", "paths": {}},
            {"swagger": "3.0", "paths": {}},
            {"openapi": "3.garbage", "paths": {}},
            {"openapi": "3.", "paths": {}},
            {"openapi": "3.0", "paths": {}},
            {"openapi": "3.0.0 garbage", "paths": {}},
        ):
            with self.subTest(unsupported=unsupported):
                result = openapi.extract_openapi(unsupported, context()).to_dict()
                self.assertEqual(result["candidates"], [])
                self.assertEqual(result["errors"][0]["code"], "invalid-openapi-document")

    def test_semver_prerelease_numeric_leading_zero_is_rejected(self) -> None:
        """SemVer numeric prerelease identifiers cannot contain leading zeroes."""
        for version in ("3.0.0-01",):
            with self.subTest(version=version):
                result = openapi.extract_openapi({"openapi": version, "paths": {}}, context()).to_dict()
                self.assertEqual(result["candidates"], [])
                self.assertEqual(result["errors"][0]["code"], "invalid-openapi-document")

    def test_semver_prerelease_and_build_metadata_remain_supported(self) -> None:
        """Valid prerelease and build identifiers remain accepted."""
        for version in ("3.0.0-0", "3.0.0-rc.1", "3.0.0+build.01"):
            with self.subTest(version=version):
                result = openapi.extract_openapi({"openapi": version, "paths": {}}, context()).to_dict()
                self.assertEqual(result["candidates"], [])
                self.assertEqual(result["errors"], [])


if __name__ == "__main__":
    unittest.main()
