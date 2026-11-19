"""Set up knowledge for the organizations made while the console had no hub (the `know` job).

A one-shot job that `infra deploy` runs after console-init when the hub is on. It does the broker's own
setup (console_app/broker/knowledge_backfill.py) with the broker's code and database role, and prints
each organization it set up, then `backfilled N organizations`. It exits non-zero if any organization
failed, after doing the ones it could; the audit log says which and why.

The job is given only what the setup uses: the database, LiteLLM's address and the admin key file, and
the knowledge settings. The broker's code also reads, at import, the settings it uses to take requests,
which the job never does; those get placeholders here.
"""

import os
import sys

_UNUSED = "https://unused.invalid"  # a reserved name: nothing is ever there
for _name, _placeholder in (("CONSOLE_PUBLIC_URL", _UNUSED), ("OIDC_ISSUER", _UNUSED), ("OIDC_JWKS_URL", _UNUSED),
                            ("OIDC_CLIENT_ID", "unused"), ("CONSOLE_BROKER_CALLER_SECRET", "unused")):
    os.environ.setdefault(_name, _placeholder)

from console_app.broker import db  # noqa: E402  (after the placeholders above)
from console_app.broker.knowledge_backfill import BackfillIncomplete, backfill  # noqa: E402


def main() -> int:
    try:
        db.pool.open(wait=True, timeout=60)
        try:
            done, failed = backfill(), []
        except BackfillIncomplete as exc:
            done, failed = exc.done, exc.failed
        finally:
            db.pool.close()
    except Exception as exc:  # never str() of others: a driver or HTTP message could carry a value
        detail = exc if isinstance(exc, RuntimeError) else type(exc).__name__
        print(f"knowledge backfill failed: {detail}", file=sys.stderr)
        return 1
    for slug in done:
        print(slug)
    for slug in failed:
        print(f"not set up: {slug} (see the audit log)", file=sys.stderr)
    print(f"backfilled {len(done)} organizations")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
