"""keycloak_db survives turning Keycloak off; other databases are untouched."""

from unittest.mock import patch

import pulumi

from llmaven.infrastructure.resources import database


def _create(names: list[str]) -> dict:
    with (
        patch.object(database.azure_native.dbforpostgresql, "Database") as db,
        patch.object(database.pulumi, "export"),
    ):
        database.create_databases(
            resource_group_name="rg",
            server_name="srv",
            database_names=names,
            environment="dev",
            tags={},
        )
    return {c.kwargs["database_name"]: c.kwargs for c in db.call_args_list}


def test_keycloak_db_is_retained_on_delete():
    kwargs = _create(["llmaven", "keycloak_db"])["keycloak_db"]
    assert isinstance(kwargs["opts"], pulumi.ResourceOptions)
    assert kwargs["opts"].retain_on_delete is True


def test_other_databases_have_no_resource_options():
    created = _create(["llmaven", "mlflow_db", "litellm_db"])
    for kwargs in created.values():
        assert "opts" not in kwargs
