"""Create the broker's LiteLLM admin key, once.

The broker must not use the master key: its key belongs to a `proxy_admin` user
and can be revoked without touching the master key. This one-shot job is the
only console piece that sees the master key. It writes the new key to a file the
broker reads, and does nothing if that file already holds a working key.
"""

import os
import secrets
import sys
from pathlib import Path

import httpx

BASE = os.environ["LITELLM_URL"]
KEY_FILE = Path(os.environ["LITELLM_ADMIN_KEY_FILE"])
USER_ID = "console-broker"


def works(key: str) -> bool:
    return httpx.get(f"{BASE}/key/info", headers={"Authorization": f"Bearer {key}"}, timeout=15).status_code == 200


def main() -> int:
    if KEY_FILE.exists() and works(KEY_FILE.read_text().strip()):
        print("broker admin key already in place")
        return 0
    master = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
    with httpx.Client(base_url=BASE, headers=master, timeout=30) as client:
        client.post("/user/new", json={"user_id": USER_ID, "user_role": "proxy_admin", "auto_create_key": False})
        response = client.post("/key/generate", json={"user_id": USER_ID,
                                                      "key_alias": f"{USER_ID}-{secrets.token_hex(4)}"})
        response.raise_for_status()
    KEY_FILE.touch(mode=0o600)
    KEY_FILE.write_text(response.json()["key"])
    print("created the broker admin key")  # never the key itself
    return 0


if __name__ == "__main__":
    sys.exit(main())
