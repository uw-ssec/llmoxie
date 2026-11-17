"""Create the broker's LiteLLM admin key, and keep only that one.

The broker must not use the master key: its key belongs to a `proxy_admin` user
and can be revoked without touching the master key. This one-shot job is the
only console piece that sees the master key. It writes the new key to a file the
broker reads, and does nothing if that file already holds a working key.

A new key is made only when LiteLLM rejects the file's key (401 or 403), or there
is no file. Any other answer, or none, fails the job and changes nothing. Before
the new key is made, the earlier broker keys are deleted, so a key left in a lost
file stops working too.
"""

import os
import re
import sys
import tempfile
from pathlib import Path

import httpx

BASE = os.environ["LITELLM_URL"]
KEY_FILE = Path(os.environ["LITELLM_ADMIN_KEY_FILE"])
USER_ID = "console-broker"
ALIAS = USER_ID
# The broker's keys: this alias, and `console-broker-<8 hex>`, which earlier versions gave each new key.
BROKER_ALIAS = re.compile(rf"{USER_ID}(-[0-9a-f]{{8}})?")


def works(client: httpx.Client, key: str) -> bool:
    """Whether LiteLLM accepts `key`. Raises when it gives no clear answer."""
    status = client.get("/key/info", headers={"Authorization": f"Bearer {key}"}).status_code
    if status in (401, 403):
        return False
    if status != 200:
        raise RuntimeError(f"LiteLLM answered the key check with HTTP {status}")
    return True


def broker_aliases(client: httpx.Client, master: dict) -> list[str]:
    aliases, page, pages = [], 1, 1
    while page <= pages:
        response = client.get("/key/list", headers=master, params={
            "user_id": USER_ID, "return_full_object": "true", "size": 100, "page": page})
        response.raise_for_status()
        listing = response.json()
        aliases += [k["key_alias"] for k in listing["keys"] if BROKER_ALIAS.fullmatch(k.get("key_alias") or "")]
        page, pages = page + 1, listing.get("total_pages") or 1
    return aliases


def write_key(key: str) -> None:
    """Replace the file in one step, so the broker never reads half a key. Readable by its owner only."""
    fd, temporary = tempfile.mkstemp(dir=KEY_FILE.parent, prefix=f".{KEY_FILE.name}-")  # mode 0600
    try:
        with os.fdopen(fd, "w") as file:
            file.write(key)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, KEY_FILE)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def main() -> int:
    try:
        with httpx.Client(base_url=BASE, timeout=30) as client:
            if KEY_FILE.exists() and works(client, KEY_FILE.read_text().strip()):
                print("broker admin key already in place")
                return 0
            master = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
            client.post("/user/new", headers=master,
                        json={"user_id": USER_ID, "user_role": "proxy_admin", "auto_create_key": False})
            earlier = broker_aliases(client, master)
            if earlier:
                client.post("/key/delete", headers=master, json={"key_aliases": earlier}).raise_for_status()
            response = client.post("/key/generate", headers=master, json={"user_id": USER_ID, "key_alias": ALIAS})
            response.raise_for_status()
        write_key(response.json()["key"])
    except (httpx.HTTPError, RuntimeError) as exc:  # never str() of an HTTP error: keep URLs and bodies out
        detail = exc if isinstance(exc, RuntimeError) else type(exc).__name__
        print(f"broker admin key not checked or made: {detail}", file=sys.stderr)
        return 1
    print(f"created the broker admin key; deleted {len(earlier)} earlier one(s)")  # never the key itself
    return 0


if __name__ == "__main__":
    sys.exit(main())
