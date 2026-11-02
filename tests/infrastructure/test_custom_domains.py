"""Custom domains configured on a container app must survive every deploy."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from llmaven.infrastructure.config.schema import LLMavenConfig
from llmaven.infrastructure.resources import container_apps


def _create_app(custom_domains):
    with (
        patch.object(
            container_apps.azure_native.app,
            "ContainerApp",
            return_value=SimpleNamespace(name="app", configuration=Mock()),
        ) as create_app,
        patch.object(
            container_apps.pulumi.Output,
            "concat",
            side_effect=lambda *parts: "".join(parts),
        ),
        patch.object(container_apps.pulumi, "export"),
    ):
        container_apps.create_container_app_with_key_vault_secrets(
            resource_group_name="rg",
            location="westus2",
            managed_environment_id="env-id",
            key_vault_uri=None,
            app_name="litellm",
            container_image="example.test/litellm:1",
            container_port=4000,
            cpu=1,
            memory="2Gi",
            min_replicas=1,
            max_replicas=2,
            custom_domains=custom_domains,
        )
    return create_app.call_args.kwargs["configuration"].ingress


def test_custom_domain_is_bound_to_existing_managed_certificate():
    config = LLMavenConfig.model_validate(
        {
            "litellm": {
                "custom_domains": [
                    {"name": "gateway.example.test", "certificate_name": "gw-cert"}
                ]
            }
        }
    )

    ingress = _create_app(config.litellm.custom_domains)

    [domain] = ingress.custom_domains
    assert domain.name == "gateway.example.test"
    assert domain.binding_type == "SniEnabled"
    assert domain.certificate_id == "env-id/managedCertificates/gw-cert"


def test_no_custom_domains_by_default():
    config = LLMavenConfig()
    assert config.litellm.custom_domains == []
    assert config.mlflow.custom_domains == []

    ingress = _create_app(config.litellm.custom_domains)

    assert ingress.custom_domains is None
