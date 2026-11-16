# The uw-ssec fork of LiteLLM (branch sso-enabled): upstream v1.108.6 with the
# 5-user Admin UI SSO cap removed, built without the proprietary enterprise/
# package. Pinned by digest; amd64 only. The version is unchanged from the
# upstream pin (v1.108.6), so the advisories already checked for it still apply.
# This build (fork commit 3867628) also sends LiteLLM's own redirects to
# PROXY_BASE_URL (llmoxie-litellm#13), which the edge needs, and has dnspython
# 2.9.2 (#14).
FROM ghcr.io/uw-ssec/llmoxie-litellm-fork:sha-386762834d2c9beea86b87a97d2be99c8885634d@sha256:bd61a2bd9aff04f21c003f123b33930ddaf423c31d3f531eb124eba104ae9d16

# The venv has no pip executable, but the bundled ensurepip works. Do not
# re-pin litellm here: that would replace the fork's patched package with
# upstream's. The assertion below fails the build if that ever happens.
# The fork ships mlflow-skinny 3.17.2, newer than the 3.6.0 MLflow server, so
# it is pinned back to the server's version. azure-storage-blob and
# azure-identity ship with the fork at compatible versions.
RUN python -m ensurepip \
 && python -m pip install --no-cache-dir "mlflow-skinny==3.6.0"

# Fails the build unless this is the fork: upstream's ui_sso defines
# _raise_if_sso_exceeds_free_user_limit, which the fork deletes.
RUN python -c "import litellm.proxy.management_endpoints.ui_sso as m; assert not hasattr(m, '_raise_if_sso_exceeds_free_user_limit'), 'SSO user cap present: not the fork'"

# The pinned-back mlflow-skinny and the fork's proxy must import together; CI
# builds this image natively on amd64 only, so the build is the only check.
# `timeout` (busybox in the fork image) fails the build on a hang instead of
# stalling CI.
RUN timeout 600 python -c "import mlflow, litellm.proxy.proxy_server"
