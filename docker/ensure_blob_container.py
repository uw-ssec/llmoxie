"""Create the MLflow artifact container in Azurite if it does not exist.

The local docker-compose stack runs this before ``mlflow server`` starts.
MLflow's Azure Blob artifact repository uploads into an existing container
but never creates one, so a fresh Azurite volume needs this step.
"""

import os
import sys
from urllib.parse import urlparse

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobServiceClient


def main() -> int:
    artifact_root = os.environ.get("MLFLOW_DEFAULT_ARTIFACT_ROOT", "")
    parsed = urlparse(artifact_root)
    if parsed.scheme != "wasbs" or "@" not in parsed.netloc:
        print(f"Artifact root is not wasbs://, skipping: {artifact_root!r}")
        return 0

    container = parsed.netloc.split("@", 1)[0]
    client = BlobServiceClient.from_connection_string(
        os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    )
    try:
        client.create_container(container)
        print(f"Created blob container {container!r}")
    except ResourceExistsError:
        print(f"Blob container {container!r} already exists")
    return 0


if __name__ == "__main__":
    sys.exit(main())
