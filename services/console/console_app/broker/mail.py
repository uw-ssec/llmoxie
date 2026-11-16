"""Outgoing mail: SMTP (Mailpit, locally) or Azure Communication Services Email (on Azure).

MAIL_BACKEND picks the backend ("smtp" by default, or "acs"). Settings are read when a message is sent, so the
broker starts without the ACS connection string when it isn't using ACS.
"""

import os
import smtplib
from email.message import EmailMessage

ACS_TIMEOUT = 30


class MailError(Exception):
    """The message could not be sent. The text never includes the address or the body."""


def _from() -> str:
    return os.environ.get("MAIL_FROM", "console@llmoxie.localhost")


def _send_smtp(to: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = _from(), to, subject
    message.set_content(body)
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "25")), timeout=10) as smtp:
        smtp.send_message(message)


def _send_acs(to: str, subject: str, body: str) -> None:
    from azure.communication.email import EmailClient

    client = EmailClient.from_connection_string(os.environ["ACS_CONNECTION_STRING"])
    client.begin_send({
        "senderAddress": _from(),
        "recipients": {"to": [{"address": to}]},
        "content": {"subject": subject, "plainText": body},
    }).result(timeout=ACS_TIMEOUT)


def send(to: str, subject: str, body: str) -> None:
    backend = os.environ.get("MAIL_BACKEND", "smtp")
    if backend not in ("smtp", "acs"):
        raise MailError(f"unknown MAIL_BACKEND {backend!r}")
    try:
        (_send_acs if backend == "acs" else _send_smtp)(to, subject, body)
    except Exception as exc:  # the backends' messages can carry the address, so say only what failed
        raise MailError(f"the {backend} mail backend failed ({type(exc).__name__})") from None
