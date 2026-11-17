"""The console's Azure Communication Services mail resources."""

import pulumi
import pytest

from llmaven.infrastructure.resources.console_mail import create_console_mail

from .test_console_config import _config
from .test_edge_app import _isolated_mocks

DOMAIN = "mail.example.org"
EMAIL_TYPE = "azure-native:communication:EmailService"
DOMAIN_TYPE = "azure-native:communication:Domain"
SENDER_TYPE = "azure-native:communication:SenderUsername"
SERVICE_TYPE = "azure-native:communication:CommunicationService"
RECORD = {"name": "@", "ttl": 3600, "type": "TXT", "value": "ms-domain-verification=x"}


class _Mocks(pulumi.runtime.Mocks):
    def __init__(self):
        self.resources: list[pulumi.runtime.MockResourceArgs] = []

    def new_resource(self, args):
        self.resources.append(args)
        outputs = dict(args.inputs)
        # Azure returns the resource's own name; the mock must too.
        own_name = {
            DOMAIN_TYPE: "domainName",
            EMAIL_TYPE: "emailServiceName",
            SERVICE_TYPE: "communicationServiceName",
        }.get(args.typ)
        if own_name:
            outputs["name"] = args.inputs[own_name]
        if args.typ == DOMAIN_TYPE:
            outputs["verificationRecords"] = {
                "domain": RECORD,
                "sPF": {**RECORD, "value": "v=spf1 include:x -all"},
            }
        return f"{args.name}-id", outputs

    def call(self, args):
        if args.token == "azure-native:communication:listCommunicationServiceKeys":
            return {"primaryConnectionString": "endpoint=https://acs/;accesskey=k"}
        return {}


@pytest.fixture
def mocks():
    recorder = _Mocks()
    with _isolated_mocks(recorder):
        yield recorder


def _create(mocks, **mail):
    config = _config(mail={"domain": DOMAIN, **mail})
    out = {}

    @pulumi.runtime.test
    def run():
        out["mail"] = create_console_mail(config, pulumi.Output.from_input("rg"), {})
        return pulumi.Output.all(
            out["mail"].connection_string, out["mail"].verification_records
        ).apply(lambda v: out.update(conn=v[0], records=v[1]))

    run()
    return out, {r.typ: r for r in mocks.resources}


def test_domain_is_customer_managed_without_tracking(mocks):
    _, res = _create(mocks)
    domain = res[DOMAIN_TYPE]
    assert domain.name == DOMAIN
    assert domain.inputs["domainName"] == DOMAIN
    assert domain.inputs["domainManagement"] == "CustomerManaged"
    assert domain.inputs["userEngagementTracking"] == "Disabled"
    assert domain.inputs["location"] == "global"
    assert res[EMAIL_TYPE].inputs["dataLocation"] == "United States"
    assert res[EMAIL_TYPE].inputs["location"] == "global"


def test_service_unlinked_until_domain_is_verified(mocks):
    _, res = _create(mocks)
    assert not res[SERVICE_TYPE].inputs.get("linkedDomains")
    assert res[SERVICE_TYPE].inputs["dataLocation"] == "United States"


def test_service_links_domain_once_verified():
    recorder = _Mocks()
    with _isolated_mocks(recorder):
        _, res = _create(recorder, domain_verified=True)
    assert res[SERVICE_TYPE].inputs["linkedDomains"] == [f"{DOMAIN}-id"]


def test_sender_address_and_username(mocks):
    out, res = _create(mocks)
    assert out["mail"].sender_address == f"console@{DOMAIN}"
    assert res[SENDER_TYPE].inputs["username"] == "console"
    assert res[SENDER_TYPE].inputs["displayName"] == "LLMoxie console"
    assert res[SENDER_TYPE].inputs["domainName"] == DOMAIN


def test_connection_string_is_a_secret_output(mocks):
    out, _ = _create(mocks)
    assert out["conn"] == "endpoint=https://acs/;accesskey=k"
    secret = {}

    @pulumi.runtime.test
    def check():
        async def gather():
            secret["v"] = await out["mail"].connection_string.is_secret()

        return gather()

    check()
    assert secret["v"] is True


def test_verification_records_are_exposed(mocks):
    out, _ = _create(mocks)
    assert out["records"]["Domain"]["value"] == "ms-domain-verification=x"
    assert out["records"]["SPF"]["type"] == "TXT"
