"""Write LiteLLM's config for the local stack: config.yaml plus what only this stack has.

config.yaml is also the base of the config the Azure deploy writes (litellm.config_file), so the
local-only parts stay out of it and are added here, when the litellm container starts:

- a mocked model, fake-gpt, that the console's end-to-end suite expects no team to be given
- disable_password_login_when_sso_enabled, which the Azure deploy adds the same way when LiteLLM's
  Keycloak login is on (src/llmaven/infrastructure/resources/helpers.py)

Usage: python local_litellm_config.py <config.yaml> <output path>
"""

import sys

import yaml


def main(source: str, target: str) -> None:
    with open(source) as handle:
        config = yaml.safe_load(handle)
    config.setdefault("model_list", []).append(
        {
            "model_name": "fake-gpt",
            "litellm_params": {
                "model": "openai/fake-gpt",
                "api_key": "sk-fake",
                "mock_response": "Hello from a mocked model",
            },
        }
    )
    config.setdefault("general_settings", {})[
        "disable_password_login_when_sso_enabled"
    ] = True
    with open(target, "w") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
