"""The console's outbound mail: Azure Communication Services Email.

An Email Communication Service holds a customer-managed domain and a sender
username. The Communication Service the broker sends through links the domain
only once ``console.mail.domain_verified`` is set, because Azure refuses to link
a domain whose DNS records are not verified yet. The first deploy therefore
creates the domain and exposes its DNS records; after they are published and
verified, setting the flag links the domain.
"""

from dataclasses import dataclass
from typing import Any

import pulumi
import pulumi_azure_native as azure_native

from ..config.schema import LLMavenConfig

# Both services are global resources; "United States" is where they keep data.
LOCATION = "global"
DATA_LOCATION = "United States"


@dataclass
class ConsoleMail:
    communication_service: azure_native.communication.CommunicationService
    domain: azure_native.communication.Domain
    sender_address: str  # f"{mail.sender}@{mail.domain}"
    connection_string: pulumi.Output[str]  # secret output
    # DNS records to publish for the domain (DKIM, DKIM2, DMARC, Domain, SPF),
    # each with name, ttl, type and value. Not secret; Task 11 exports it.
    verification_records: pulumi.Output[dict[str, dict[str, Any]]]


def _records_by_kind(records: Any) -> dict[str, dict[str, Any]]:
    """The domain's DNS records as plain dicts keyed by their kind."""
    by_kind = {
        "Domain": records.domain,
        "SPF": records.s_pf,
        "DKIM": records.d_kim,
        "DKIM2": records.d_kim2,
        "DMARC": records.d_marc,
    }
    return {
        kind: {
            "name": record.name,
            "ttl": record.ttl,
            "type": record.type,
            "value": record.value,
        }
        for kind, record in by_kind.items()
        if record is not None
    }


def create_console_mail(
    config: LLMavenConfig, resource_group_name: pulumi.Input[str], tags: dict[str, str]
) -> ConsoleMail:
    mail = config.console.mail
    assert mail.domain is not None  # validated when the console is enabled
    project = config.project.name
    environment = config.project.environment

    email_service = azure_native.communication.EmailService(
        f"console-email-{environment}",
        email_service_name=f"{project}-{environment}-mail",
        resource_group_name=resource_group_name,
        location=LOCATION,
        data_location=DATA_LOCATION,
        tags=tags,
    )
    # Azure requires the Domain resource to be named after the domain itself.
    domain = azure_native.communication.Domain(
        mail.domain,
        domain_name=mail.domain,
        email_service_name=email_service.name,
        resource_group_name=resource_group_name,
        location=LOCATION,
        domain_management=azure_native.communication.DomainManagement.CUSTOMER_MANAGED,
        user_engagement_tracking=azure_native.communication.UserEngagementTracking.DISABLED,
        tags=tags,
    )
    azure_native.communication.SenderUsername(
        f"console-sender-{environment}",
        sender_username=mail.sender,
        username=mail.sender,
        display_name=mail.display_name,
        domain_name=domain.name,
        email_service_name=email_service.name,
        resource_group_name=resource_group_name,
    )

    service = azure_native.communication.CommunicationService(
        f"console-acs-{environment}",
        communication_service_name=f"{project}-{environment}-acs",
        resource_group_name=resource_group_name,
        location=LOCATION,
        data_location=DATA_LOCATION,
        linked_domains=[domain.id] if mail.domain_verified else None,
        tags=tags,
        opts=pulumi.ResourceOptions(
            depends_on=[domain] if mail.domain_verified else None
        ),
    )
    keys = azure_native.communication.list_communication_service_keys_output(
        communication_service_name=service.name,
        resource_group_name=resource_group_name,
    )
    return ConsoleMail(
        communication_service=service,
        domain=domain,
        sender_address=f"{mail.sender}@{mail.domain}",
        connection_string=pulumi.Output.secret(keys.primary_connection_string),
        verification_records=domain.verification_records.apply(
            _records_by_kind
        ),
    )
