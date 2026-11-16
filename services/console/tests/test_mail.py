"""The broker's outgoing mail: SMTP by default, Azure Communication Services when asked. No stack needed."""

import smtplib
from email.message import EmailMessage

import pytest

from .test_knowledge_off import ORG_ID, _Tx, app_client, broker_env_without_hub, calls  # noqa: F401

ADDRESS = "a@x.org"


@pytest.fixture
def mail(broker_env_without_hub, monkeypatch):  # noqa: F811
    monkeypatch.delenv("MAIL_BACKEND", raising=False)
    monkeypatch.delenv("ACS_CONNECTION_STRING", raising=False)
    monkeypatch.setenv("MAIL_FROM", "console@llmoxie.test")
    from console_app.broker import mail
    return mail


@pytest.fixture
def fake_smtp(monkeypatch):
    sent: list[EmailMessage] = []

    class SMTP:
        def __init__(self, host, port, timeout):
            self.host, self.port = host, port

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr(smtplib, "SMTP", SMTP)
    return sent


@pytest.fixture
def fake_email_client(monkeypatch):
    import azure.communication.email as acs

    seen = {"messages": [], "timeouts": []}

    class Poller:
        def result(self, timeout=None):
            seen["timeouts"].append(timeout)
            return {"status": "Succeeded"}

    class Client:
        @classmethod
        def from_connection_string(cls, connection_string):
            seen["connection_string"] = connection_string
            return cls()

        def begin_send(self, message):
            seen["messages"].append(message)
            return Poller()

    monkeypatch.setattr(acs, "EmailClient", Client)
    return seen


def test_smtp_is_the_default(mail, fake_smtp):
    mail.send(ADDRESS, "s", "b")
    assert fake_smtp[0]["To"] == ADDRESS
    assert fake_smtp[0]["From"] == "console@llmoxie.test"
    assert fake_smtp[0]["Subject"] == "s" and fake_smtp[0].get_content().strip() == "b"


def test_acs_sends_with_connection_string(mail, monkeypatch, fake_email_client):
    monkeypatch.setenv("MAIL_BACKEND", "acs")
    monkeypatch.setenv("ACS_CONNECTION_STRING", "endpoint=https://acs.test/;accesskey=k")
    mail.send(ADDRESS, "s", "b")
    assert fake_email_client["connection_string"] == "endpoint=https://acs.test/;accesskey=k"
    assert fake_email_client["messages"] == [{
        "senderAddress": "console@llmoxie.test",
        "recipients": {"to": [{"address": ADDRESS}]},
        "content": {"subject": "s", "plainText": "b"},
    }]
    assert fake_email_client["timeouts"] == [30]


def test_acs_failure_raises_mail_error_without_address(mail, monkeypatch):
    import azure.communication.email as acs

    class Client:
        @classmethod
        def from_connection_string(cls, _):
            return cls()

        def begin_send(self, message):
            raise RuntimeError(f"cannot deliver to {message['recipients']['to'][0]['address']}: body here")

    monkeypatch.setattr(acs, "EmailClient", Client)
    monkeypatch.setenv("MAIL_BACKEND", "acs")
    monkeypatch.setenv("ACS_CONNECTION_STRING", "endpoint=https://acs.test/;accesskey=k")
    with pytest.raises(mail.MailError) as caught:
        mail.send(ADDRESS, "s", "body here")
    assert ADDRESS not in str(caught.value) and "body here" not in str(caught.value)


def test_acs_without_connection_string_is_a_mail_error(mail, monkeypatch):
    monkeypatch.setenv("MAIL_BACKEND", "acs")
    with pytest.raises(mail.MailError):
        mail.send(ADDRESS, "s", "b")


def test_smtp_failure_is_a_mail_error(mail, monkeypatch):
    def refuse(*_, **__):
        raise OSError(f"refused for {ADDRESS}")

    monkeypatch.setattr(smtplib, "SMTP", refuse)
    with pytest.raises(mail.MailError) as caught:
        mail.send(ADDRESS, "s", "b")
    assert ADDRESS not in str(caught.value)


def test_unknown_backend_is_a_mail_error(mail, monkeypatch):
    monkeypatch.setenv("MAIL_BACKEND", "carrier-pigeon")
    with pytest.raises(mail.MailError):
        mail.send(ADDRESS, "s", "b")


@pytest.fixture
def invites(monkeypatch):
    """Counts the invite rows the broker writes, and sends the mail through a switch that can fail."""
    from console_app.broker import db, mail

    log = {"revoked": 0, "created": 0, "sent": 0, "fail": True}

    class Conn:
        def execute(self, sql, params=None):
            from .test_knowledge_off import _Conn
            if "SET status = 'revoked'" in sql:
                log["revoked"] += 1
            if "INSERT INTO invite" in sql:
                log["created"] += 1
            return _Conn().execute(sql, params)

    class Tx(_Tx):
        def __enter__(self):
            return Conn()

    def send(to, subject, body):
        if log["fail"]:
            raise mail.MailError("the acs mail backend failed (RuntimeError)")
        log["sent"] += 1

    monkeypatch.setattr(db, "org_tx", lambda _org_id: Tx())
    monkeypatch.setattr(mail, "send", send)
    return log


def test_invite_mail_failure_is_502_mail_failed(app_client, invites):  # noqa: F811
    r = app_client.post(f"/admin/orgs/{ORG_ID}/leads", json={"email": ADDRESS})
    assert r.status_code == 502
    assert r.json() == {"error": "mail_failed", "message": "The email could not be sent. Try again later."}


def test_reinvite_after_mail_failure_works(app_client, invites):  # noqa: F811
    assert app_client.post(f"/admin/orgs/{ORG_ID}/leads", json={"email": ADDRESS}).status_code == 502
    invites["fail"] = False
    r = app_client.post(f"/admin/orgs/{ORG_ID}/leads", json={"email": ADDRESS})
    assert r.status_code == 200 and r.json() == {"invited": ADDRESS}
    # Each attempt revokes any pending invite for the address before it adds its own; mail went out once.
    assert invites["revoked"] == 2 and invites["created"] == 2 and invites["sent"] == 1
