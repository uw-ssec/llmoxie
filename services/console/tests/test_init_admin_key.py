"""init_admin_key.py against a stand-in for LiteLLM's key API, so these run without a stack."""

import os
import stat

import httpx
import pytest

os.environ.setdefault("LITELLM_URL", "http://litellm.test")
os.environ.setdefault("LITELLM_ADMIN_KEY_FILE", "/nonexistent/admin-key")

import init_admin_key  # noqa: E402

MASTER = "sk-master-test"


class FakeLiteLLM:
    """Keys by alias, for the broker's user and one other; answers as LiteLLM 1.108 does."""

    def __init__(self):
        self.keys = {"console-broker-1a2b3c4d": ("console-broker", "sk-old-1"),  # what earlier versions made
                     "console-broker-9f8e7d6c": ("console-broker", "sk-old-2"),
                     "someone-else": ("console-broker", "sk-manual"),            # not ours to delete
                     "c-participant": ("p_123", "sk-participant")}
        self.check = None  # an HTTP status, or an exception, to answer /key/info with instead
        self.generate_status = 200
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(path)
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
        if path == "/key/info":
            if isinstance(self.check, Exception):
                raise self.check
            if self.check:
                return httpx.Response(self.check)
            return httpx.Response(200 if bearer in {k for _, k in self.keys.values()} else 401)
        assert bearer == MASTER, path
        body = request.read() and __import__("json").loads(request.content)
        if path == "/user/new":
            return httpx.Response(400)  # the user exists
        if path == "/key/list":
            user = request.url.params["user_id"]
            keys = [{"key_alias": a, "user_id": u} for a, (u, _) in self.keys.items() if u == user]
            return httpx.Response(200, json={"keys": keys, "total_pages": 1})
        if path == "/key/delete":
            for alias in body["key_aliases"]:
                del self.keys[alias]
            return httpx.Response(200, json={})
        if path == "/key/generate":
            if self.generate_status != 200:
                return httpx.Response(self.generate_status)
            if body["key_alias"] in self.keys:
                return httpx.Response(400)  # aliases are unique
            self.keys[body["key_alias"]] = (body["user_id"], "sk-new")
            return httpx.Response(200, json={"key": "sk-new"})
        return httpx.Response(404)


@pytest.fixture
def litellm(monkeypatch, tmp_path):
    fake = FakeLiteLLM()
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(fake), **kw))
    monkeypatch.setattr(init_admin_key, "KEY_FILE", tmp_path / "admin-key")
    monkeypatch.setenv("LITELLM_MASTER_KEY", MASTER)
    return fake


def test_a_working_key_is_kept(litellm):
    init_admin_key.KEY_FILE.write_text("sk-old-1")
    assert init_admin_key.main() == 0
    assert init_admin_key.KEY_FILE.read_text() == "sk-old-1" and "/key/generate" not in litellm.calls


@pytest.mark.parametrize("answer", [500, 503, httpx.ConnectError("refused"), httpx.ReadTimeout("slow")])
def test_no_new_key_when_litellm_cannot_say(litellm, answer):
    init_admin_key.KEY_FILE.write_text("sk-old-1")
    litellm.check = answer
    assert init_admin_key.main() != 0
    assert init_admin_key.KEY_FILE.read_text() == "sk-old-1"
    assert "/key/generate" not in litellm.calls and "/key/delete" not in litellm.calls


@pytest.mark.parametrize("rejected", ["sk-revoked", None])  # a key LiteLLM rejects, or no file at all
def test_a_replacement_retires_every_earlier_broker_key(litellm, rejected):
    if rejected:
        init_admin_key.KEY_FILE.write_text(rejected)
    assert init_admin_key.main() == 0
    assert init_admin_key.KEY_FILE.read_text() == "sk-new"
    assert stat.S_IMODE(init_admin_key.KEY_FILE.stat().st_mode) == 0o600
    assert list(init_admin_key.KEY_FILE.parent.iterdir()) == [init_admin_key.KEY_FILE]  # no temporary file left
    assert litellm.keys == {"console-broker": ("console-broker", "sk-new"),
                            "someone-else": ("console-broker", "sk-manual"),
                            "c-participant": ("p_123", "sk-participant")}
    assert init_admin_key.main() == 0 and litellm.calls.count("/key/generate") == 1  # a second run keeps it


def test_a_failed_replacement_leaves_the_file_alone(litellm):
    init_admin_key.KEY_FILE.write_text("sk-revoked")
    litellm.generate_status = 500
    assert init_admin_key.main() != 0
    assert init_admin_key.KEY_FILE.read_text() == "sk-revoked"
    assert list(init_admin_key.KEY_FILE.parent.iterdir()) == [init_admin_key.KEY_FILE]
