"""Data loss prevention: ceil-dlp reads every chat request in LiteLLM before it leaves for a model.

The policy is litellm/ceil-dlp.yaml. These tests use a mock model, so what the model was sent is read
from the request log (one JSON file per request in Azurite), which is written after ceil-dlp has run.
"""

import json
import os
import time
import uuid

import httpx
import pytest
from azure.storage.blob import ContainerClient

from .helpers import access_token, broker, create_user, sign_in

RUN = uuid.uuid4().hex[:8]
GATEWAY = os.environ["GATEWAY_URL"]
LITELLM = os.environ["LITELLM_URL"]
MASTER = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
MODEL = f"dlp-test-{RUN}"
CARD, SSN = "4111 1111 1111 1111", "536-90-4399"
API_KEY = "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKL"
EMAIL, PHONE = f"jane.doe.{RUN}@example.org", "+1 415 555 0132"
W: dict = {}


@pytest.fixture(scope="module", autouse=True)
def mock_model_and_key():
    """A mock model and a key for it, made straight in LiteLLM; the console is not what is tested here."""
    model = httpx.post(f"{LITELLM}/model/new", headers=MASTER, json={
        "model_name": MODEL, "litellm_params": {"model": "openai/x", "api_key": "sk-x", "mock_response": "A mocked reply"}}).json()
    W["key"] = httpx.post(f"{LITELLM}/key/generate", headers=MASTER, json={"models": [MODEL]}).json()["key"]
    yield
    httpx.post(f"{LITELLM}/key/delete", headers=MASTER, json={"keys": [W["key"]]})
    httpx.post(f"{LITELLM}/model/delete", headers=MASTER, json={"id": model["model_id"]})


def ask(content: str, **more):
    return httpx.post(f"{GATEWAY}/v1/chat/completions", headers={"Authorization": f"Bearer {W['key']}"}, timeout=60,
                      json={"model": MODEL, "messages": [{"role": "user", "content": content}], **more})


def logged(marker: str) -> str:
    """The request log of the call whose prompt holds `marker`."""
    container = ContainerClient.from_connection_string(os.environ["AZURE_STORAGE_CONNECTION_STRING"], "litellm-logs")
    deadline = time.time() + 40
    while time.time() < deadline:
        for blob in sorted(container.list_blobs(), key=lambda b: b.last_modified, reverse=True)[:40]:
            record = container.download_blob(blob.name).readall().decode()
            if marker in record:
                return record
        time.sleep(2)
    raise AssertionError("no request log in Azurite")


def test_an_ordinary_request_goes_through_untouched():
    marker = f"PLAIN-{RUN}"
    answer = ask(f"{marker} Please summarise the meeting with Dr. Alice Johnson in Seattle on 3 March.")
    assert answer.status_code == 200 and answer.json()["choices"][0]["message"]["content"] == "A mocked reply"
    # Names, places and dates have no policy, so they are left alone.
    record = logged(marker)
    assert "Alice Johnson" in record and "Seattle" in record and "REDACTED" not in record


@pytest.mark.parametrize("what,text", [("credit_card", f"Charge my card {CARD} please"),
                                       ("ssn", f"My social security number is {SSN}"),
                                       ("pem_key", "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA7\n-----END RSA PRIVATE KEY-----")])  # pragma: allowlist secret
@pytest.mark.parametrize("stream", [False, True])
def test_what_must_never_leave_is_refused(what, text, stream):
    refused = ask(text, stream=stream)
    assert refused.status_code == 400, refused.text
    error = refused.json()["error"]
    assert "[ceil-dlp] Request blocked" in error["message"] and what in error["message"]
    assert error["provider_specific_fields"]["guardrail_name"] == "ceil-dlp"    # LiteLLM says which guardrail refused
    assert CARD not in refused.text and SSN not in refused.text       # the refusal does not repeat the value


def test_a_pasted_credential_is_hidden_from_the_model():
    marker = f"MASK-{RUN}"
    answer = ask(f"{marker} Why does this fail? client = OpenAI(api_key='{API_KEY}')")
    assert answer.status_code == 200
    record = logged(marker)
    assert "[REDACTED_API_KEY]" in record and API_KEY not in record


def test_contact_details_are_swapped_for_stand_ins():
    marker = f"SWAP-{RUN}"
    answer = ask(f"{marker} Draft a reply to {EMAIL}, or I can call them on {PHONE}.")
    assert answer.status_code == 200
    record = logged(marker)
    assert EMAIL not in record and PHONE not in record and "EMAIL_1" in record and "PHONE_1" in record


def test_streamed_replies_arrive_whole_and_in_order():
    with httpx.stream("POST", f"{GATEWAY}/v1/chat/completions", headers={"Authorization": f"Bearer {W['key']}"}, timeout=60,
                      json={"model": MODEL, "stream": True, "messages": [{"role": "user", "content": f"write to {EMAIL}"}]}) as response:
        assert response.status_code == 200
        lines = [line for line in response.iter_lines() if line.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    chunks = [json.loads(line[6:]) for line in lines[:-1]]
    text = "".join((c["choices"][0]["delta"].get("content") or "") for c in chunks if c.get("choices"))
    assert text == "A mocked reply"
    # The end of a stream is held back and sent last. No text may come after the chunk that ends the reply.
    ends = [i for i, c in enumerate(chunks) if c.get("choices") and c["choices"][0].get("finish_reason")]
    assert ends and all(not (c.get("choices") and c["choices"][0]["delta"].get("content")) for c in chunks[ends[0] + 1:])


def test_litellm_lists_it_as_a_guardrail_that_is_on_for_everyone():
    listed = httpx.get(f"{LITELLM}/guardrails/list", headers=MASTER).json()["guardrails"]
    mine = [g for g in listed if g["guardrail_name"] == "ceil-dlp"]
    assert len(mine) == 1 and mine[0]["litellm_params"]["default_on"] is True
    assert set(mine[0]["litellm_params"]["mode"]) == {"pre_call", "post_call"}


def test_admins_see_what_was_found_and_never_the_values():
    alice = sign_in("alice@example.com", "alice123")
    assert alice.api_get("/session").json()["me"]["is_admin"] is True   # what puts "Data protection" in the menu
    page = alice.api_get("/admin/dlp")
    assert page.status_code == 200
    shown = page.json()
    assert set(shown) == {"enabled", "read", "shown", "actions", "totals", "events"} and shown["enabled"] is True
    kinds = {t["kind"] for t in shown["totals"]} | {k for e in shown["events"] for k in e["kinds"]}
    assert kinds >= {"credit_card", "ssn", "pem_key", "api_key", "email", "phone"}
    # The words the page uses for each action, and the mark that makes it say "request refused".
    assert shown["actions"]["mask"] == "hidden from the model" and shown["actions"]["whistledown"] == "swapped for a stand-in"
    assert any(e["blocked"] for e in shown["events"])
    assert all(set(e) == {"at", "kinds", "blocked", "action", "source", "mode", "count", "email", "user_id", "request"}
               and len(e["request"]) <= 8 for e in shown["events"])
    view = broker("GET", "/admin/dlp", access_token("alice@example.com", "alice123")).json()
    assert view["enabled"] and {(t["kind"], t["action"]) for t in view["totals"]} >= {
        ("credit_card", "blocked"), ("ssn", "blocked"), ("api_key", "mask"), ("email", "whistledown")}
    assert any(e["blocked"] and e["kinds"] == ["credit_card"] for e in view["events"])
    for secret in (CARD, SSN, API_KEY, EMAIL, PHONE):
        assert secret not in page.text and secret not in json.dumps(view)

    # Admins only.
    create_user(f"dlp-{RUN}@example.com", "Correct-horse-9")
    outsider = sign_in(f"dlp-{RUN}@example.com", "Correct-horse-9")
    assert outsider.api_get("/admin/dlp").status_code == 403
    assert outsider.api_get("/session").json()["me"]["is_admin"] is False
    assert broker("GET", "/admin/dlp", access_token(f"dlp-{RUN}@example.com", "Correct-horse-9")).status_code == 403
