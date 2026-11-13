#!/usr/bin/env bash
# Create (or start) the local k3s clusters and install the llmoxie chart.
#
# Prototype for #236. Two clusters run in Docker through k3d:
#   llmoxie         the llmoxie release
#   llmoxie-backup  only an S3 store for database backups, standing in for the
#                   separate place a real site keeps them
# Their kubeconfigs are written under .kube/ and never merged into
# ~/.kube/config.
set -euo pipefail

CLUSTER="llmoxie"
BACKUP_CLUSTER="llmoxie-backup"
NETWORK="llmoxie-local" # shared Docker network, so one cluster can reach the other
NAMESPACE="llmoxie"
CNPG_CHART_VERSION="0.29.1" # CloudNativePG operator 1.30.1

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export KUBECONFIG="${root}/.kube/llmoxie-k3s.yaml"
backup_kubeconfig="${root}/.kube/llmoxie-backup-k3s.yaml"
# Pinned helm and kubectl wrappers.
export PATH="${root}/scripts/k3s/bin:${PATH}"

docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK" >/dev/null

# Create a cluster, or start it if it exists, and write its kubeconfig.
#
# k3s can lose a first-boot race (its cloud-controller-manager starts before the
# bootstrap RBAC exists) and then shuts down on every start; `k3d --wait` does
# not notice. A cluster that was just created holds no data, so it is recreated
# once. An existing cluster is never deleted here.
ensure_cluster() {
    local name="$1" kubeconfig="$2"
    shift 2
    if k3d cluster get "$name" >/dev/null 2>&1; then
        k3d cluster start "$name"
        k3d kubeconfig get "$name" >"$kubeconfig"
        chmod 600 "$kubeconfig"
        return 0
    fi
    local attempt
    for attempt in 1 2; do
        k3d cluster create "$name" \
            --servers 1 \
            --network "$NETWORK" \
            --kubeconfig-update-default=false \
            --kubeconfig-switch-context=false \
            --wait --timeout 180s \
            "$@"
        k3d kubeconfig get "$name" >"$kubeconfig"
        chmod 600 "$kubeconfig"
        if node_ready "$kubeconfig"; then
            return 0
        fi
        echo "k3s in cluster ${name} did not stay up (attempt ${attempt}); deleting it" >&2
        k3d cluster delete "$name"
    done
    echo "could not create cluster ${name}" >&2
    return 1
}

# True once the cluster's node reports Ready; false if the API never answers.
node_ready() {
    local kubeconfig="$1" try
    for try in $(seq 1 12); do
        if KUBECONFIG="$kubeconfig" kubectl get nodes --output name 2>/dev/null | grep -q .; then
            KUBECONFIG="$kubeconfig" kubectl wait --for=condition=Ready nodes --all --timeout=120s
            return
        fi
        sleep 5
    done
    return 1
}

mkdir -p "$(dirname "$KUBECONFIG")"
# LiteLLM and MLflow are published on loopback only, on the same host ports the
# docker-compose stack uses, through pinned NodePorts.
# The service images are loaded from the host, not pulled from a registry, so
# the kubelet must not garbage-collect them: under disk pressure it deleted the
# backup image between job runs, and a loaded image cannot be pulled again.
ensure_cluster "$CLUSTER" "$KUBECONFIG" \
    --port "127.0.0.1:4000:30400@server:0" \
    --port "127.0.0.1:8080:30080@server:0" \
    --k3s-arg "--kubelet-arg=image-gc-high-threshold=100@server:0"
ensure_cluster "$BACKUP_CLUSTER" "$backup_kubeconfig" \
    --k3s-arg "--disable=traefik@server:0"

# Backup store: RustFS in the backup cluster, reachable from the main cluster at
# http://k3d-llmoxie-backup-server-0:30900. Its keys are generated once.
backup_kubectl() { KUBECONFIG="$backup_kubeconfig" kubectl --namespace backup-store "$@"; }
backup_kubectl create namespace backup-store --dry-run=client --output yaml | backup_kubectl apply --filename - >/dev/null
if ! backup_kubectl get secret backup-store-keys >/dev/null 2>&1; then
    backup_kubectl create secret generic backup-store-keys \
        --from-literal=access-key="llmoxie$(openssl rand -hex 6)" \
        --from-literal=secret-key="$(openssl rand -hex 20)"
fi
backup_kubectl apply --filename "${root}/scripts/k3s/backup-store.yaml"
backup_kubectl rollout status statefulset/backup-store --timeout 180s

# Hand the backup store's keys to the llmoxie release.
kubectl create namespace "$NAMESPACE" --dry-run=client --output yaml | kubectl apply --filename - >/dev/null
kubectl --namespace "$NAMESPACE" create secret generic llmoxie-backup-storage \
    --from-literal=access-key="$(backup_kubectl get secret backup-store-keys --output jsonpath='{.data.access-key}' | base64 -d)" \
    --from-literal=secret-key="$(backup_kubectl get secret backup-store-keys --output jsonpath='{.data.secret-key}' | base64 -d)" \
    --dry-run=client --output yaml | kubectl apply --filename - >/dev/null

# Build the service images from the local Dockerfiles, as docker-compose did,
# and load them into the cluster. Each tag is a hash of the image's inputs, so
# pods roll only when an image changed. Prints the tag.
build_image() {
    local name="$1" context="$2" dockerfile="$3"
    shift 3
    local tag image
    tag="$(cat "$dockerfile" "$@" | shasum -a 256 | cut -c1-12)"
    image="llmoxie-local/${name}:${tag}"
    if ! docker image inspect "$image" >/dev/null 2>&1; then
        docker build --tag "$image" --file "$dockerfile" "$context" >&2
    fi
    if ! docker exec "k3d-${CLUSTER}-server-0" crictl inspecti "docker.io/${image}" >/dev/null 2>&1; then
        k3d image import "$image" --cluster "$CLUSTER" >&2
    fi
    echo "$tag"
}

dockerfiles="${root}/docker/dockerfiles"
litellm_tag="$(build_image litellm "${root}/docker" "${dockerfiles}/litellm.dockerfile")"
mlflow_tag="$(build_image mlflow "${root}/docker" "${dockerfiles}/mlflow.dockerfile")"
backup_tag="$(build_image backup "$root" "${dockerfiles}/backup.dockerfile" "${root}/scripts/backup_postgres.py")"

# Cluster layer: operators installed once per cluster, outside the llmoxie chart.
helm upgrade --install cnpg cloudnative-pg \
    --repo https://cloudnative-pg.github.io/charts \
    --version "$CNPG_CHART_VERSION" \
    --namespace cnpg-system --create-namespace \
    --wait --timeout 5m

# llmoxie release.
helm upgrade --install llmoxie "${root}/charts/llmoxie" \
    --namespace "$NAMESPACE" --create-namespace \
    --values "${root}/charts/llmoxie/ci/k3s-values.yaml" \
    --set "litellm.image.repository=llmoxie-local/litellm,litellm.image.tag=${litellm_tag}" \
    --set "mlflow.image.repository=llmoxie-local/mlflow,mlflow.image.tag=${mlflow_tag}" \
    --set "backup.image.repository=llmoxie-local/backup,backup.image.tag=${backup_tag}" \
    --wait --timeout 15m

# k3d adds the backup cluster's node name to this cluster's DNS a minute or two
# after creation. Return only once a pod here can reach the backup store.
reachable=""
for _ in $(seq 1 60); do
    if kubectl --namespace "$NAMESPACE" exec deploy/llmoxie-litellm --container litellm -- \
        python -c "import socket; socket.create_connection(('k3d-${BACKUP_CLUSTER}-server-0', 30900), 3)" \
        >/dev/null 2>&1; then
        reachable=1
        break
    fi
    sleep 5
done
if [[ -z "$reachable" ]]; then
    echo "the backup store is not reachable from the ${CLUSTER} cluster" >&2
    exit 1
fi

kubectl --namespace "$NAMESPACE" get pods
