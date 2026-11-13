# One image for console-web, console-broker and console-init; the command picks which.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt
COPY console_app console_app
COPY init_admin_key.py .
# /run/console holds the LiteLLM admin key; the volume mounted there inherits this ownership.
RUN useradd --uid 10001 --no-create-home console && mkdir /run/console && chown console /run/console
USER console

FROM app AS tests
USER root
COPY requirements-test.txt .
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements-test.txt
COPY tests tests
USER console
CMD ["pytest", "-q", "tests"]
