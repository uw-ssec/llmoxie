# The pages: the React application in frontend/, built to static files. Nothing from this stage but
# those files reaches the image below.
FROM node:24-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54 AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend .
RUN npm run build -- --outDir /ui/dist

# One image for console-web, console-broker and console-init; the command picks which.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt
COPY console_app console_app
COPY --from=ui /ui/dist console_app/web/dist
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
