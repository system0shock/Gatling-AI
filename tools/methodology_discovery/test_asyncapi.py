"""Behavioral tests for bounded AsyncAPI extraction."""

from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import patch

if __package__:
    from . import asyncapi, contracts
else:
    import asyncapi
    import contracts


SHA256 = "2" * 64


def context(repo_id: str = "orders-events", service_id: str | None = "orders") -> dict:
    return {
        "repo_id": repo_id,
        "snapshot_identity": "commit:fedcba9876543210",
        "service_id": service_id,
        "source": {
            "repo_id": repo_id,
            "revision": "fedcba9876543210",
            "path": "api/asyncapi.yaml",
            "pointer": "#",
            "selection_reason": "asyncapi-signature",
            "sha256": SHA256,
        },
    }


class AsyncApiExtractorTests(unittest.TestCase):
    def test_resolved_asyncapi_key_collision_is_visible_and_deterministic(self) -> None:
        """Two operations on one channel/direction must not remain silently ambiguous."""
        operations = [
            ("sendA", {"action": "send", "channel": {"$ref": "#/channels/created"}}),
            ("sendB", {"action": "send", "channel": {"$ref": "#/channels/created"}}),
        ]
        document = {
            "asyncapi": "3.0.0",
            "info": {"title": "Orders"},
            "channels": {"created": {"address": "document.created"}},
            "operations": dict(operations),
        }
        reversed_document = document | {"operations": dict(reversed(operations))}

        first = asyncapi.extract_asyncapi(document, context()).to_dict()
        second = asyncapi.extract_asyncapi(reversed_document, context()).to_dict()

        self.assertEqual(first, second)
        self.assertEqual(len(first["candidates"]), 2)
        self.assertEqual(
            {candidate["canonical_key"] for candidate in first["candidates"]},
            {"message:orders:document.created:publish"},
        )
        self.assertEqual([warning["code"] for warning in first["warnings"]], ["canonical-key-collision"])

    def test_explicit_invalid_contract_service_id_is_unknown_not_title_metadata(self) -> None:
        """AsyncAPI shares the explicit invalid-identity boundary with OpenAPI."""
        document = {
            "asyncapi": "2.6.0",
            "info": {"title": "Orders Metadata", "x-service-id": ""},
            "channels": {"created": {"publish": {"message": {"name": "Created"}}}},
        }

        result = asyncapi.extract_asyncapi(document, context(service_id=None)).to_dict()

        candidate = result["candidates"][0]
        self.assertEqual(candidate["service_identity"], {"value": "repo-orders-events", "basis": "unknown"})
        self.assertEqual(candidate["canonical_key"], "message:repo-orders-events:created:publish")
        self.assertEqual([warning["code"] for warning in result["warnings"]], ["invalid-service-identity"])

    def test_cyclic_message_one_of_is_diagnostic_and_valid_sibling_survives(self) -> None:
        """A YAML-alias cycle must not recurse forever or erase another operation."""
        cyclic_message: dict = {}
        cyclic_message["oneOf"] = [cyclic_message]
        document = {
            "asyncapi": "2.6.0",
            "info": {"title": "Orders"},
            "channels": {
                "bad": {"publish": {"message": cyclic_message}},
                "good": {"subscribe": {"message": {"name": "GoodMessage"}}},
            },
        }

        result = asyncapi.extract_asyncapi(document, context()).to_dict()

        self.assertEqual(
            [candidate["canonical_key"] for candidate in result["candidates"]],
            ["message:orders:bad:publish", "message:orders:good:subscribe"],
        )
        self.assertEqual(result["candidates"][1]["attributes"]["message_names"], ["GoodMessage"])
        self.assertEqual([warning["code"] for warning in result["warnings"]], ["cyclic-message-one-of"])
        contracts.validate_artifact(result, "methodology-extractor-result.schema.json")

    def test_deep_acyclic_message_one_of_is_iterative_and_keeps_message_name(self) -> None:
        """A bounded but deeply nested acyclic oneOf must not hit Python recursion."""
        message: dict = {"name": "DeepMessage"}
        for _ in range(2_000):
            message = {"oneOf": [message]}
        document = {
            "asyncapi": "2.6.0",
            "info": {"title": "Orders"},
            "channels": {"deep": {"publish": {"message": message}}},
        }

        result = asyncapi.extract_asyncapi(document, context()).to_dict()

        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["candidates"][0]["attributes"]["message_names"], ["DeepMessage"])
        contracts.validate_artifact(result, "methodology-extractor-result.schema.json")

    def test_caller_supplied_json_and_safe_yaml_text_are_parsed_in_memory(self) -> None:
        """Valid bounded text must parse safely while unsafe YAML becomes an error."""
        texts = (
            '{"asyncapi":"2.6.0","info":{"title":"Orders"},"channels":{"json":{"publish":{"message":{"name":"Json"}}}}}',
            "asyncapi: 2.6.0\ninfo:\n  title: Orders\nchannels:\n  yaml:\n    subscribe:\n      message:\n        name: Yaml\n",
        )
        expected = ("message:orders:json:publish", "message:orders:yaml:subscribe")
        for text, canonical_key in zip(texts, expected, strict=True):
            with self.subTest(canonical_key=canonical_key):
                result = asyncapi.extract_asyncapi(text, context()).to_dict()
                self.assertEqual(result["errors"], [])
                self.assertEqual(result["candidates"][0]["canonical_key"], canonical_key)

        for unsafe in ("!!python/object/apply:builtins.str [unsafe]", "asyncapi: ["):
            with self.subTest(unsafe=unsafe):
                result = asyncapi.extract_asyncapi(unsafe, context()).to_dict()
                self.assertEqual(result["candidates"], [])
                self.assertEqual(result["errors"][0]["code"], "invalid-asyncapi-document")

    def test_v2_publish_subscribe_operations_are_local_interface_facts(self) -> None:
        """Changing direction, messages, tags, or emitting a flow must fail."""
        document = {
            "asyncapi": "2.6.0",
            "info": {"title": "Orders Events", "x-service-id": "orders"},
            "servers": {"prod": {"url": "broker.example.test", "protocol": "kafka"}},
            "channels": {
                "document.created": {
                    "publish": {
                        "operationId": "emitCreated",
                        "tags": [{"name": "documents"}, {"name": "write"}],
                        "message": {"name": "DocumentCreated"},
                    },
                    "subscribe": {"message": {"oneOf": [{"name": "DocumentCreated"}, {"name": "DocumentReplayed"}]}},
                }
            },
        }
        original = deepcopy(document)

        result = asyncapi.extract_asyncapi(document, context()).to_dict()

        self.assertEqual(document, original)
        self.assertEqual([candidate["canonical_key"] for candidate in result["candidates"]], [
            "message:orders:document.created:publish",
            "message:orders:document.created:subscribe",
        ])
        published = result["candidates"][0]
        self.assertEqual(published["entity_type"], "interface")
        self.assertEqual(published["service_identity"], {"value": "orders", "basis": "contract"})
        self.assertEqual(published["attributes"], {
            "channel": "document.created",
            "direction": "publish",
            "message_names": ["DocumentCreated"],
            "operation": "publish document.created",
            "operation_id": "emitCreated",
            "protocol": "AsyncAPI",
            "servers": ["prod:kafka:broker.example.test"],
            "tags": ["documents", "write"],
        })
        self.assertEqual(result["candidates"][1]["attributes"]["message_names"], ["DocumentCreated", "DocumentReplayed"])
        self.assertTrue(all(candidate["entity_type"] != "flow" for candidate in result["candidates"]))
        self.assertNotIn("size_bytes", published["source"])
        contracts.validate_artifact(result, "methodology-extractor-result.schema.json")

    def test_v3_send_receive_actions_use_channel_map_without_perspective_guessing(self) -> None:
        """Breaking v3 channel references or send/receive normalization must fail."""
        document = {
            "asyncapi": "3.0.0",
            "info": {"title": "Orders Events"},
            "channels": {
                "created": {"address": "document.created", "messages": {"created": {"name": "DocumentCreated"}}},
                "audit": {"address": "document.audit", "messages": {"audit": {"name": "DocumentAudited"}}},
            },
            "operations": {
                "receiveAudit": {"action": "receive", "channel": {"$ref": "#/channels/audit"}, "messages": [{"$ref": "#/channels/audit/messages/audit"}]},
                "sendCreated": {"action": "send", "channel": {"$ref": "#/channels/created"}, "messages": [{"$ref": "#/channels/created/messages/created"}]},
                "observeCreated": {"channel": {"$ref": "#/channels/created"}},
                "broken": "not-an-operation",
            },
        }

        result = asyncapi.extract_asyncapi(document, context(service_id=None)).to_dict()

        self.assertEqual([candidate["canonical_key"] for candidate in result["candidates"]], [
            "message:orders-events:document.audit:subscribe",
            "message:orders-events:document.created:publish",
            "message:orders-events:document.created:unspecified",
        ])
        self.assertEqual([candidate["attributes"]["direction"] for candidate in result["candidates"]], ["subscribe", "publish", "unspecified"])
        self.assertEqual(result["candidates"][0]["attributes"]["message_names"], ["DocumentAudited"])
        self.assertEqual(result["candidates"][1]["attributes"]["message_names"], ["DocumentCreated"])
        self.assertEqual([warning["code"] for warning in result["warnings"]], ["malformed-operation"])
        contracts.validate_artifact(result, "methodology-extractor-result.schema.json")

    def test_channel_send_receive_keys_and_malformed_siblings_remain_deterministic(self) -> None:
        """A malformed channel sibling must not erase valid send/receive operations."""
        document = {
            "asyncapi": "3.0.0",
            "info": {"title": "Orders"},
            "channels": {
                "z": {"send": {"operationId": "sendZ", "message": {"name": "Zed"}}, "receive": {"message": {"name": "Zed"}}},
                "bad": "not-a-channel",
            },
        }
        first = asyncapi.extract_asyncapi(document, context()).to_dict()
        second = asyncapi.extract_asyncapi(deepcopy(document), context()).to_dict()

        self.assertEqual(first, second)
        self.assertEqual([candidate["attributes"]["direction"] for candidate in first["candidates"]], ["publish", "subscribe"])
        self.assertEqual([warning["code"] for warning in first["warnings"]], ["malformed-channel"])

    def test_conflict_remote_ref_and_invalid_top_level_are_bounded_diagnostics(self) -> None:
        """Identity conflict and remote refs must remain repo-scoped and never fetch."""
        document = {
            "asyncapi": "2.6.0",
            "info": {"title": "Billing", "x-service-id": "billing"},
            "channels": {
                "remote": {"$ref": "https://example.invalid/channel.yaml"},
                "valid": {"publish": {"message": {"$ref": "https://example.invalid/messages.yaml"}}},
            },
        }
        with patch("urllib.request.urlopen", side_effect=AssertionError("network fetch")):
            result = asyncapi.extract_asyncapi(document, context(service_id="orders")).to_dict()

        self.assertEqual(result["candidates"][0]["canonical_key"], "message:repo-orders-events:valid:publish")
        self.assertEqual(result["candidates"][0]["service_identity"]["basis"], "unknown")
        self.assertEqual([warning["code"] for warning in result["warnings"]], ["reference-not-resolved", "service-identity-conflict"])
        invalid = asyncapi.extract_asyncapi("asyncapi: 3.0.0", context()).to_dict()
        self.assertEqual(invalid["candidates"], [])
        self.assertEqual(invalid["errors"][0]["code"], "invalid-asyncapi-document")
        self.assertNotIn("Traceback", invalid["errors"][0]["message"])
        contracts.validate_artifact(invalid, "methodology-extractor-result.schema.json")

        for unsupported in (
            {"asyncapi": "1.2.0", "channels": {}},
            {"asyncapi": "4.0.0", "channels": {}},
            {"asyncapi": "3.garbage", "channels": {}},
            {"asyncapi": "2.", "channels": {}},
            {"asyncapi": "3.0", "channels": {}},
            {"asyncapi": "2.6.0 garbage", "channels": {}},
        ):
            with self.subTest(unsupported=unsupported):
                result = asyncapi.extract_asyncapi(unsupported, context()).to_dict()
                self.assertEqual(result["candidates"], [])
                self.assertEqual(result["errors"][0]["code"], "invalid-asyncapi-document")


if __name__ == "__main__":
    unittest.main()
