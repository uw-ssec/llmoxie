{{- define "llmoxie.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 40 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 40 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 40 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/* Labels for every object. Call with (list $ "component"). */}}
{{- define "llmoxie.labels" -}}
{{- $root := index . 0 -}}
helm.sh/chart: {{ printf "%s-%s" $root.Chart.Name $root.Chart.Version }}
app.kubernetes.io/managed-by: {{ $root.Release.Service }}
app.kubernetes.io/part-of: llmoxie
{{ include "llmoxie.selectorLabels" . }}
{{- end }}

{{- define "llmoxie.selectorLabels" -}}
{{- $root := index . 0 -}}
app.kubernetes.io/name: llmoxie
app.kubernetes.io/instance: {{ $root.Release.Name }}
app.kubernetes.io/component: {{ index . 1 }}
{{- end }}

{{/* Reject values the chart cannot honor. Included once, from litellm.yaml. */}}
{{- define "llmoxie.validate" -}}
{{- if not (has .Values.postgres.mode (list "bundled" "external")) }}
{{- fail "postgres.mode must be bundled or external" }}
{{- end }}
{{- if not (has .Values.redis.mode (list "bundled" "external" "disabled")) }}
{{- fail "redis.mode must be bundled, external or disabled" }}
{{- end }}
{{- if not (has .Values.objectStorage.mode (list "bundled" "external")) }}
{{- fail "objectStorage.mode must be bundled or external" }}
{{- end }}
{{- if and (gt (int .Values.litellm.replicas) 1) (eq .Values.redis.mode "disabled") }}
{{- fail "litellm.replicas > 1 needs Redis: rate limits and budgets are per replica without it. Set redis.mode to bundled or external." }}
{{- end }}
{{- if and (not .Values.litellm.keys.existingSecret) (not .Values.litellm.keys.generate) }}
{{- fail "litellm.keys.existingSecret is required: a Secret with `master-key` and `salt-key`, kept in the site's secret store. A restore needs the same salt key. For a throwaway stack, set litellm.keys.generate=true." }}
{{- end }}
{{- if .Values.backup.enabled }}
{{- if not .Values.backup.storage.existingSecret }}
{{- fail "backup.enabled needs a destination outside this cluster: set backup.storage.existingSecret (and backup.storage.endpoint unless it is AWS S3), or set backup.enabled=false." }}
{{- end }}
{{- if and (eq .Values.objectStorage.mode "bundled") (eq .Values.backup.storage.endpoint (include "llmoxie.objectStorage.endpoint" .)) }}
{{- fail "backup.storage.endpoint points at this release's bundled object storage. Backups must live outside the cluster." }}
{{- end }}
{{- end }}
{{- if and (eq .Values.postgres.mode "bundled") (not (.Capabilities.APIVersions.Has "postgresql.cnpg.io/v1")) }}
{{- fail "postgres.mode=bundled needs the CloudNativePG operator on the cluster. Install it first, or set postgres.mode=external." }}
{{- end }}
{{- end }}

{{/* ---------- LiteLLM keys ---------- */}}

{{- define "llmoxie.litellm.keysSecret" -}}
{{ default (printf "%s-litellm-keys" (include "llmoxie.fullname" .)) .Values.litellm.keys.existingSecret }}
{{- end }}

{{/* ---------- PostgreSQL ---------- */}}

{{- define "llmoxie.postgres.secretName" -}}
{{- if eq .Values.postgres.mode "bundled" -}}
{{ include "llmoxie.fullname" . }}-postgres-app
{{- else -}}
{{ required "postgres.external.existingSecret is required when postgres.mode=external" .Values.postgres.external.existingSecret }}
{{- end -}}
{{- end }}

{{/* PG* variables from the connection Secret (CloudNativePG's key names). */}}
{{- define "llmoxie.postgres.env" -}}
{{- $secret := include "llmoxie.postgres.secretName" . -}}
- name: PGHOST
  valueFrom:
    secretKeyRef: { name: {{ $secret }}, key: host }
- name: PGPORT
  valueFrom:
    secretKeyRef: { name: {{ $secret }}, key: port }
- name: PGUSER
  valueFrom:
    secretKeyRef: { name: {{ $secret }}, key: username }
- name: PGPASSWORD
  valueFrom:
    secretKeyRef: { name: {{ $secret }}, key: password }
{{- end }}

{{/* Init container that blocks until PostgreSQL accepts connections.
     Call with (list $ .Values.<component>.image). The image needs Python. */}}
{{- define "llmoxie.postgres.wait" -}}
{{- $root := index . 0 -}}
{{- $image := index . 1 -}}
- name: wait-for-postgres
  image: "{{ $image.repository }}:{{ $image.tag }}"
  imagePullPolicy: {{ $image.pullPolicy }}
  command:
    - python
    - -c
    - |
      import os, socket, time
      address = (os.environ["PGHOST"], int(os.environ["PGPORT"]))
      while True:
          try:
              socket.create_connection(address, timeout=3).close()
              break
          except OSError as exc:
              print(f"waiting for postgres at {address}: {exc}", flush=True)
              time.sleep(3)
  env:
    {{- include "llmoxie.postgres.env" $root | nindent 4 }}
{{- end }}

{{/* ---------- Redis ---------- */}}

{{- define "llmoxie.redis.secretName" -}}
{{- if eq .Values.redis.mode "bundled" -}}
{{ include "llmoxie.fullname" . }}-redis
{{- else -}}
{{ required "redis.external.existingSecret is required when redis.mode=external" .Values.redis.external.existingSecret }}
{{- end -}}
{{- end }}

{{- define "llmoxie.redis.host" -}}
{{- if eq .Values.redis.mode "bundled" -}}
{{ include "llmoxie.fullname" . }}-redis
{{- else -}}
{{ required "redis.external.host is required when redis.mode=external" .Values.redis.external.host }}
{{- end -}}
{{- end }}

{{/* ---------- Object storage (S3 API) ---------- */}}

{{- define "llmoxie.objectStorage.secretName" -}}
{{- if eq .Values.objectStorage.mode "bundled" -}}
{{ include "llmoxie.fullname" . }}-object-storage
{{- else -}}
{{ required "objectStorage.external.existingSecret is required when objectStorage.mode=external" .Values.objectStorage.external.existingSecret }}
{{- end -}}
{{- end }}

{{/* Empty for AWS S3 itself; set for RustFS and other S3-compatible servers. */}}
{{- define "llmoxie.objectStorage.endpoint" -}}
{{- if eq .Values.objectStorage.mode "bundled" -}}
http://{{ include "llmoxie.fullname" . }}-object-storage:9000
{{- else -}}
{{ .Values.objectStorage.external.endpoint }}
{{- end -}}
{{- end }}

{{/* The standard AWS variables, which boto3, s3fs and MLflow all read. */}}
{{- define "llmoxie.objectStorage.env" -}}
{{- $secret := include "llmoxie.objectStorage.secretName" . -}}
{{- $endpoint := include "llmoxie.objectStorage.endpoint" . -}}
- name: AWS_ACCESS_KEY_ID
  valueFrom:
    secretKeyRef: { name: {{ $secret }}, key: access-key }
- name: AWS_SECRET_ACCESS_KEY
  valueFrom:
    secretKeyRef: { name: {{ $secret }}, key: secret-key }
- name: AWS_DEFAULT_REGION
  value: {{ .Values.objectStorage.region | quote }}
{{- if $endpoint }}
- name: AWS_ENDPOINT_URL
  value: {{ $endpoint | quote }}
{{- end }}
{{- end }}

{{/* Python that waits for object storage and creates a bucket only if it is
     missing, so pre-created buckets on external storage are left alone.
     Needs boto3. Call with the bucket name. */}}
{{- define "llmoxie.objectStorage.ensureBucket" -}}
import sys, time
import boto3
from botocore.exceptions import ClientError, EndpointConnectionError
bucket = {{ . | quote }}
client = boto3.client("s3")
for attempt in range(60):
    try:
        client.head_bucket(Bucket=bucket)
        print(f"bucket {bucket!r} exists")
        break
    except EndpointConnectionError as exc:
        print(f"waiting for object storage: {exc}", flush=True)
        time.sleep(3)
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in ("404", "NoSuchBucket"):
            raise
        client.create_bucket(Bucket=bucket)
        print(f"created bucket {bucket!r}")
        break
else:
    sys.exit("object storage never became reachable")
{{- end }}

{{/* ---------- Backup storage (S3 API, outside the cluster) ---------- */}}

{{- define "llmoxie.backup.env" -}}
{{- $storage := .Values.backup.storage -}}
- name: AWS_ACCESS_KEY_ID
  valueFrom:
    secretKeyRef: { name: {{ $storage.existingSecret }}, key: access-key }
- name: AWS_SECRET_ACCESS_KEY
  valueFrom:
    secretKeyRef: { name: {{ $storage.existingSecret }}, key: secret-key }
- name: AWS_DEFAULT_REGION
  value: {{ $storage.region | quote }}
{{- if $storage.endpoint }}
- name: AWS_ENDPOINT_URL
  value: {{ $storage.endpoint | quote }}
{{- end }}
{{- end }}

{{/* ---------- Generated secrets ---------- */}}

{{/* Keep a generated value stable: reuse what is already in the cluster.
     Call with (list $ "secret-name" "key" "prefix" length). */}}
{{- define "llmoxie.generatedValue" -}}
{{- $root := index . 0 -}}
{{- $existing := lookup "v1" "Secret" $root.Release.Namespace (index . 1) -}}
{{- if and $existing (hasKey $existing.data (index . 2)) -}}
{{ index $existing.data (index . 2) }}
{{- else -}}
{{ printf "%s%s" (index . 3) (randAlphaNum (index . 4)) | b64enc }}
{{- end -}}
{{- end }}
