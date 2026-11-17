"""What console-web's access log keeps of an address. Pure functions, so these run without a stack."""

import logging

from uvicorn.logging import AccessFormatter

from console_app.web import access_log

TOKEN = "Zq3-x_SENTINEL_TOKEN_0123456789abcdefghijk"


def logged(path: str) -> str:
    """The access log line uvicorn writes for a GET of `path`, after the console's filter."""
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                               ("10.0.0.1:5000", "GET", path, "1.1", 200), None)
    assert access_log.Redact().filter(record) is True  # the line is kept
    return AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False).format(record)


def test_invitation_tokens_are_redacted():
    for path, shown in ((f"/invite/{TOKEN}", "/invite/<redacted>"),
                        (f"/Invite/{TOKEN}?x=1", "/Invite/<redacted>?x=1"),
                        (f"/web-api/invites/{TOKEN}", "/web-api/invites/<redacted>")):
        line = logged(path)
        assert TOKEN not in line and f'"GET {shown} HTTP/1.1" 200' in line, line


def test_sign_in_codes_and_state_are_dropped():
    line = logged(f"/auth/callback?state={TOKEN}&session_state=s&code={TOKEN}")
    assert TOKEN not in line and '"GET /auth/callback HTTP/1.1"' in line
    assert TOKEN not in logged(f"/somewhere?code={TOKEN}")
    assert TOKEN not in logged(f"/somewhere?a=1&STATE={TOKEN}")


def test_other_addresses_are_kept_as_they_are():
    for path in ("/teams/3de6981a/manage", "/?next=%2Fteams", "/web-api/session", "/invite-result/invalid"):
        assert f'"GET {path} HTTP/1.1"' in logged(path)


def test_console_web_installs_the_filter_on_uvicorns_access_log():
    access_log.install()
    assert any(isinstance(f, access_log.Redact) for f in logging.getLogger("uvicorn.access").filters)
