"""Behavioral tests for bounded deployment and build metadata extraction."""

from __future__ import annotations

import unittest

if __package__:
    from . import contracts, deployment
else:
    import contracts
    import deployment


SHA256 = "2" * 64


def context(path: str = "deploy/all.yaml", reason: str = "kubernetes-signature") -> dict:
    return {
        "repo_id": "orders-infra",
        "snapshot_identity": "commit:0123456789abcdef",
        "service_id": "orders",
        "source": {
            "repo_id": "orders-infra",
            "revision": "0123456789abcdef",
            "path": path,
            "pointer": "#",
            "selection_reason": reason,
            "sha256": SHA256,
        },
    }


class DeploymentExtractorTests(unittest.TestCase):
    def test_declared_ports_validate_bounds_ranges_protocols_and_original_pointers(self) -> None:
        documents = [
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": "orders-api"},
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [{
                                "name": "api",
                                "ports": [
                                    {"containerPort": True},
                                    {"containerPort": 70_000},
                                    {"containerPort": 8080, "protocol": "UDP"},
                                    {"containerPort": 8081, "protocol": True},
                                    {"containerPort": 8082, "protocol": "invalid"},
                                ],
                            }]
                        }
                    }
                },
            },
            {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": "orders-dns"},
                "spec": {
                    "ports": [
                        {"port": 80, "targetPort": False},
                        {"port": 53, "targetPort": 5353, "protocol": "UDP"},
                        {"port": 54, "targetPort": 70_000},
                    ]
                },
            },
        ]

        result = deployment.extract_deployment(documents, context()).to_dict()
        ports = [item for item in result["candidates"] if item["entity_type"] == "interface"]

        self.assertEqual(
            {(item["attributes"]["port"], item["attributes"]["protocol"]) for item in ports},
            {(53, "UDP"), (8080, "UDP")},
        )
        self.assertEqual(
            {item["source"]["pointer"] for item in ports},
            {
                "#/documents/0/spec/template/spec/containers/0/ports/2",
                "#/documents/1/spec/ports/1",
            },
        )

    def test_compose_ports_keep_bounded_ranges_and_reject_malformed_explicit_fields(self) -> None:
        document = {
            "name": "orders-stack",
            "services": {
                "api": {
                    "ports": [
                        True,
                        "0:80",
                        "70000:80",
                        "8000-8002:80-82/udp",
                        "8000-900000:80-82/tcp",
                        {"target": 53, "published": 5353, "protocol": "udp"},
                        {"target": 80, "published": "9000-9002", "protocol": "tcp"},
                        {"target": 53, "published": True},
                        {"target": True},
                        {"target": 80, "protocol": True},
                        "8080:80/sctp",
                        "9" * 5_000,
                    ]
                }
            },
        }

        result = deployment.extract_deployment(
            document, context("compose.yaml", "docker-compose-signature")
        ).to_dict()
        ports = [item for item in result["candidates"] if item["entity_type"] == "interface"]

        self.assertEqual(len(ports), 3)
        self.assertEqual(
            {
                (
                    item["attributes"]["port"],
                    item["attributes"].get("target_port"),
                    item["attributes"]["protocol"],
                )
                for item in ports
            },
            {
                ("8000-8002", "80-82", "UDP"),
                (5353, 53, "UDP"),
                ("9000-9002", 80, "TCP"),
            },
        )
        self.assertIn(
            "#/documents/0/services/api/ports/3",
            {item["source"]["pointer"] for item in ports},
        )

    def test_kubernetes_and_openshift_objects_emit_only_explicit_local_facts(self) -> None:
        documents = [
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": "orders-api"},
                "spec": {
                    "template": {
                        "metadata": {"labels": {"app": "orders"}},
                        "spec": {"containers": [{"name": "api", "ports": [{"containerPort": 8080}]}]},
                    }
                },
            },
            {
                "apiVersion": "apps/v1",
                "kind": "StatefulSet",
                "metadata": {"name": "orders-db"},
                "spec": {"template": {"metadata": {"labels": {"app": "db"}}, "spec": {"containers": []}}},
            },
            {
                "apiVersion": "apps.openshift.io/v1",
                "kind": "DeploymentConfig",
                "metadata": {"name": "orders-worker"},
                "spec": {"template": {"metadata": {"labels": {"app": "worker"}}, "spec": {"containers": []}}},
            },
            {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": "orders"},
                "spec": {"selector": {"app": "orders"}, "ports": [{"name": "http", "port": 80, "targetPort": 8080}]},
            },
            {
                "apiVersion": "networking.k8s.io/v1",
                "kind": "Ingress",
                "metadata": {"name": "orders-public"},
                "spec": {"rules": [{"host": "orders.example.test", "http": {"paths": [{"path": "/orders"}]}}]},
            },
            {
                "apiVersion": "route.openshift.io/v1",
                "kind": "Route",
                "metadata": {"name": "orders-route"},
                "spec": {"host": "route.example.test", "path": "/api", "to": {"name": "orders"}},
            },
            {
                "apiVersion": "route.openshift.io/v1",
                "kind": "Route",
                "metadata": {"name": "cluster-assigned-route"},
                "spec": {"to": {"name": "orders"}},
            },
        ]

        result = deployment.extract_deployment(documents, context()).to_dict()

        contracts.validate_artifact(result, "methodology-extractor-result.schema.json")
        components = [item for item in result["candidates"] if item["entity_type"] == "component"]
        interfaces = [item for item in result["candidates"] if item["entity_type"] == "interface"]
        integrations = [item for item in result["candidates"] if item["entity_type"] == "integration"]
        self.assertEqual({item["display_name"] for item in components}, {"orders-api", "orders-db", "orders-worker"})
        self.assertIn(("orders-api", 8080), {(item["attributes"].get("owner"), item["attributes"].get("port")) for item in interfaces})
        self.assertIn(("orders", 80), {(item["attributes"].get("owner"), item["attributes"].get("port")) for item in interfaces})
        self.assertEqual(
            {item["attributes"].get("host") for item in interfaces if "host" in item["attributes"]},
            {"orders.example.test", "route.example.test"},
        )
        self.assertEqual(len(integrations), 1)
        self.assertEqual(integrations[0]["attributes"]["source"], "orders")
        self.assertEqual(integrations[0]["attributes"]["target"], "orders-api")
        self.assertTrue(all(item["source"]["pointer"].startswith("#/documents/") for item in result["candidates"]))
        self.assertIn("cluster-assigned-route", {item["attributes"].get("owner") for item in interfaces})

    def test_selector_integration_requires_explicit_matching_labels(self) -> None:
        documents = [
            {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "unlabelled"}, "spec": {"template": {"spec": {"containers": []}}}},
            {"apiVersion": "v1", "kind": "Service", "metadata": {"name": "no-selector"}, "spec": {"ports": [{"port": 80}]}},
            {"apiVersion": "v1", "kind": "Service", "metadata": {"name": "wrong-selector"}, "spec": {"selector": {"app": "other"}, "ports": []}},
        ]

        result = deployment.extract_deployment(documents, context()).to_dict()

        self.assertEqual([item for item in result["candidates"] if item["entity_type"] == "integration"], [])

    def test_malformed_or_unnamed_siblings_warn_without_hiding_valid_objects(self) -> None:
        yaml_text = """\
apiVersion: apps/v1
kind: Deployment
metadata: {}
---
- malformed
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: valid-api
spec:
  template:
    spec:
      containers: []
"""

        result = deployment.extract_deployment(yaml_text, context()).to_dict()

        self.assertEqual([item["display_name"] for item in result["candidates"]], ["valid-api"])
        self.assertIn("stable-name-required", {item["code"] for item in result["warnings"]})
        self.assertIn("malformed-deployment-document", {item["code"] for item in result["warnings"]})

    def test_compose_emits_service_ports_and_only_explicit_dependencies(self) -> None:
        document = {
            "name": "orders-stack",
            "services": {
                "api": {"ports": ["127.0.0.1:8080:80/tcp"], "depends_on": {"db": {"condition": "service_started"}}, "environment": {"KAFKA_TOPIC": "invented.topic"}},
                "db": {"image": "postgres:16"},
                "worker": {"image": "worker"},
            },
        }

        result = deployment.extract_deployment(document, context("compose.yaml", "docker-compose-signature")).to_dict()

        self.assertEqual(
            {item["display_name"] for item in result["candidates"] if item["entity_type"] == "component"},
            {"api", "db", "worker"},
        )
        interface = next(item for item in result["candidates"] if item["entity_type"] == "interface")
        self.assertEqual(interface["attributes"]["port"], 8080)
        integrations = [item for item in result["candidates"] if item["entity_type"] == "integration"]
        self.assertEqual([(item["attributes"]["source"], item["attributes"]["target"]) for item in integrations], [("api", "db")])
        self.assertNotIn("invented.topic", str(result))

    def test_spring_stream_requires_a_literal_destination_not_bootstrap_servers(self) -> None:
        document = {
            "spring": {
                "cloud": {"stream": {"bindings": {"orders-out-0": {"destination": "orders.created"}}}},
                "kafka": {"bootstrap-servers": "localhost:9092"},
            }
        }
        properties = """\
spring.kafka.bootstrap-servers=localhost:9092
spring.cloud.stream.bindings.audit-in-0.destination=audit.events
spring.cloud.stream.bindings.dynamic.destination=${TOPIC_NAME}
"""

        yaml_result = deployment.extract_deployment(document, context("application.yaml", "spring-configuration-signature")).to_dict()
        yaml_text_result = deployment.extract_build_metadata(
            "spring:\n  cloud:\n    stream:\n      bindings:\n        orders-out-0:\n          destination: orders.created\n",
            "application.yaml",
            context("application.yaml", "spring-configuration-signature"),
        ).to_dict()
        properties_result = deployment.extract_build_metadata(properties, "application.properties", context("application.properties", "spring-configuration-signature")).to_dict()

        yaml_integrations = [item for item in yaml_result["candidates"] if item["entity_type"] == "integration"]
        properties_integrations = [item for item in properties_result["candidates"] if item["entity_type"] == "integration"]
        self.assertEqual([item["attributes"]["destination"] for item in yaml_integrations], ["orders.created"])
        self.assertEqual([item["attributes"]["destination"] for item in yaml_text_result["candidates"]], ["orders.created"])
        self.assertEqual([item["attributes"]["destination"] for item in properties_integrations], ["audit.events"])
        self.assertNotIn("localhost:9092", str(yaml_result["candidates"]) + str(properties_result["candidates"]))
        self.assertIn("dynamic-destination", {warning["code"] for warning in properties_result["warnings"]})

    def test_uppercase_destination_is_literal_and_build_path_must_match_provenance(self) -> None:
        result = deployment.extract_build_metadata(
            "spring.cloud.stream.bindings.orders.destination=ORDERS",
            "application.properties",
            context("application.properties", "spring-configuration-signature"),
        ).to_dict()

        self.assertEqual(result["candidates"][0]["attributes"]["destination"], "ORDERS")
        with self.assertRaisesRegex(ValueError, "context source path"):
            deployment.extract_build_metadata(
                "<project><artifactId>orders</artifactId></project>",
                "pom.xml",
                context("application.properties", "spring-configuration-signature"),
            )

    def test_chart_maven_and_gradle_use_only_declared_project_metadata(self) -> None:
        chart = deployment.extract_build_metadata(
            "apiVersion: v2\nname: orders-chart\nappVersion: 1.2.3\ndependencies:\n  - name: redis\n",
            "Chart.yaml",
            context("Chart.yaml", "helm-chart-signature"),
        ).to_dict()
        pom = deployment.extract_build_metadata(
            """<project><artifactId>orders-api</artifactId><dependencies><dependency><artifactId>fake-interface</artifactId></dependency></dependencies><build><plugins><plugin><artifactId>spring-boot-maven-plugin</artifactId></plugin></plugins></build></project>""",
            "pom.xml",
            context("pom.xml", "maven-build-signature"),
        ).to_dict()
        gradle = deployment.extract_build_metadata(
            """rootProject.name = 'orders-worker'\nplugins { id 'org.springframework.boot' version '3.4.0' }\ndependencies { implementation 'org.example:fake-interface:1.0' }\n""",
            "settings.gradle",
            context("settings.gradle", "gradle-build-signature"),
        ).to_dict()

        self.assertEqual(chart["candidates"][0]["attributes"], {"app_version": "1.2.3", "kind": "helm-chart", "name": "orders-chart"})
        self.assertEqual(chart["candidates"][0]["source"]["pointer"], "#/documents/0/name")
        self.assertEqual(pom["candidates"][0]["attributes"]["artifact_id"], "orders-api")
        self.assertEqual(pom["candidates"][0]["attributes"]["markers"], ["spring-boot-maven-plugin"])
        self.assertEqual(gradle["candidates"][0]["attributes"]["root_project_name"], "orders-worker")
        self.assertEqual(gradle["candidates"][0]["attributes"]["markers"], ["org.springframework.boot"])
        self.assertTrue(all(item["entity_type"] == "component" for result in (chart, pom, gradle) for item in result["candidates"]))
        self.assertNotIn("fake-interface", str(chart["candidates"]) + str(pom["candidates"]) + str(gradle["candidates"]))

    def test_gradle_comments_do_not_declare_root_or_plugins(self) -> None:
        text = """\
// rootProject.name = 'commented-root'
/*
rootProject.name = 'blocked-root'
plugins { id 'blocked.plugin' }
*/
rootProject.name = 'real-root' // keep the real declaration
plugins {
  // id 'line.comment.plugin'
  id 'real.plugin'
}
def endpoint = "https://example.test/path" // comment markers in strings are data
"""

        result = deployment.extract_build_metadata(
            text,
            "settings.gradle",
            context("settings.gradle", "gradle-build-signature"),
        ).to_dict()

        self.assertEqual(result["candidates"][0]["display_name"], "real-root")
        self.assertEqual(result["candidates"][0]["attributes"]["markers"], ["real.plugin"])
        self.assertEqual(result["candidates"][0]["source"]["pointer"], "#L6")


if __name__ == "__main__":
    unittest.main()
