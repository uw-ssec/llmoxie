"""Azure AI Foundry (AIServices) account and model deployments.

The account's data plane accepts traffic only from the Container Apps
environment subnet: ``networkAcls`` denies by default, bypasses no trusted
services, has no IP rules, and has exactly one virtual network rule for that
subnet. The subnet needs the ``Microsoft.CognitiveServices`` service endpoint
(see ``FOUNDRY_SERVICE_ENDPOINT``). Management-plane (ARM) calls, which Pulumi
uses, are not affected by these rules.
"""

from typing import Dict, List, Optional, Tuple

import pulumi
import pulumi_azure_native as azure_native
from pulumi import Output

from ..config.schema import LLMavenConfig

FOUNDRY_SERVICE_ENDPOINT = "Microsoft.CognitiveServices"


def foundry_account_name(config: LLMavenConfig) -> str:
    """Return the configured account name, or the default derived from the project."""
    return (
        config.foundry.account_name
        or f"{config.project.name}-foundry-{config.project.environment}"
    )


def create_foundry(
    resource_group_name: Output[str],
    location: str,
    allowed_subnet_id: Output[str],
    config: LLMavenConfig,
    tags: Optional[Dict[str, str]] = None,
    opts: Optional[pulumi.ResourceOptions] = None,
) -> Tuple[
    azure_native.cognitiveservices.Account,
    List[azure_native.cognitiveservices.Deployment],
]:
    """Create the Foundry account and one deployment per configured model.

    Args:
        resource_group_name: Resource group name
        location: Region used when ``foundry.location`` is unset
        allowed_subnet_id: The only subnet allowed to reach the data plane
        config: LLMaven configuration (``config.foundry`` must be enabled)
        tags: Resource tags
        opts: Options for the account (e.g. depends_on the subnet)

    Returns:
        The account and its deployments, in creation order
    """
    environment = config.project.environment
    account_name = foundry_account_name(config)

    account = azure_native.cognitiveservices.Account(
        f"foundry-account-{environment}",
        resource_group_name=resource_group_name,
        account_name=account_name,
        location=config.foundry.location or location,
        kind="AIServices",
        sku=azure_native.cognitiveservices.SkuArgs(name=config.foundry.sku),
        properties=azure_native.cognitiveservices.AccountPropertiesArgs(
            custom_sub_domain_name=account_name,
            # "Enabled" plus a Deny ACL means "selected networks only".
            # "Disabled" would require a private endpoint.
            public_network_access="Enabled",
            network_acls=azure_native.cognitiveservices.NetworkRuleSetArgs(
                default_action="Deny",
                bypass="None",
                ip_rules=[],
                virtual_network_rules=[
                    azure_native.cognitiveservices.VirtualNetworkRuleArgs(
                        id=allowed_subnet_id,
                        ignore_missing_vnet_service_endpoint=False,
                    )
                ],
            ),
            # API key auth: LiteLLM reads the key from Key Vault (azure-api-key).
            disable_local_auth=False,
        ),
        tags=tags,
        opts=opts,
    )

    # Azure rejects concurrent deployment operations on one account, so chain them.
    deployments: List[azure_native.cognitiveservices.Deployment] = []
    previous: Optional[pulumi.Resource] = None
    for spec in config.foundry.deployments:
        deployment = azure_native.cognitiveservices.Deployment(
            f"foundry-deployment-{spec.name}-{environment}",
            resource_group_name=resource_group_name,
            account_name=account.name,
            deployment_name=spec.name,
            sku=azure_native.cognitiveservices.SkuArgs(
                name=spec.sku, capacity=spec.capacity
            ),
            properties=azure_native.cognitiveservices.DeploymentPropertiesArgs(
                model=azure_native.cognitiveservices.DeploymentModelArgs(
                    format=spec.model_format,
                    name=spec.model_name,
                    version=spec.model_version,
                ),
                version_upgrade_option=spec.version_upgrade_option,
            ),
            tags=tags,
            opts=pulumi.ResourceOptions(depends_on=[previous] if previous else None),
        )
        deployments.append(deployment)
        previous = deployment

    pulumi.export("foundry_account_name", account.name)
    pulumi.export("foundry_endpoint", foundry_openai_endpoint(account_name))
    pulumi.export("foundry_deployments", [d.name for d in config.foundry.deployments])

    return account, deployments


def foundry_openai_endpoint(account_name: str) -> str:
    """Azure OpenAI endpoint for an account's custom subdomain."""
    return f"https://{account_name}.openai.azure.com/"


def get_foundry_api_key(
    resource_group_name: Output[str],
    account: azure_native.cognitiveservices.Account,
) -> Output[str]:
    """Return the account's primary key as a Pulumi secret."""
    keys = azure_native.cognitiveservices.list_account_keys_output(
        resource_group_name=resource_group_name,
        account_name=account.name,
    )
    return Output.secret(keys.key1)
