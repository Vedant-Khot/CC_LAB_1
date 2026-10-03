#!/usr/bin/env bash
# Builds the three service images and pushes them to Docker Hub.
#
#   ./publish.sh                       reads IMAGE_PREFIX from .env
#   IMAGE_PREFIX=<yourhubusername> ./publish.sh
#
# Log in first:  docker login     (nothing is stored in this repository)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# pick up IMAGE_PREFIX / IMAGE_TAG from .env if it exists
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . "./.env"
  set +a
fi

SERVICES=(registration-service opportunity-service evaluation-service)

if ! docker info >/dev/null 2>&1; then
  echo "docker engine is not reachable - start Docker Desktop and retry" >&2
  exit 1
fi

if [ -z "${IMAGE_PREFIX:-}" ] || [ "$IMAGE_PREFIX" = "yourhubusername" ]; then
  echo "set IMAGE_PREFIX to your Docker Hub username, e.g." >&2
  echo "  echo 'IMAGE_PREFIX=<yourhubusername>' >> .env" >&2
  exit 1
fi

IMAGE_TAG="${IMAGE_TAG:-latest}"
echo "pushing as docker.io/$IMAGE_PREFIX/<service>:$IMAGE_TAG"
echo

for service in "${SERVICES[@]}"; do
  if docker manifest inspect "$IMAGE_PREFIX/$service:$IMAGE_TAG" >/dev/null 2>&1; then
    echo "note: $IMAGE_PREFIX/$service:$IMAGE_TAG already exists on Docker Hub"
  elif ! grep -qs 'docker.io' "${DOCKER_CONFIG:-$HOME/.docker}/config.json" 2>/dev/null; then
    echo "warning: no docker.io credentials found - run 'docker login' first" >&2
  fi
done

echo
echo "building..."
docker compose build

echo
echo "pushing..."
for service in "${SERVICES[@]}"; do
  echo "-> $IMAGE_PREFIX/$service:$IMAGE_TAG"
  docker push "$IMAGE_PREFIX/$service:$IMAGE_TAG"
done

echo
echo "local images:"
docker images --format '{{.Repository}}:{{.Tag}}  {{.Size}}' | grep "$IMAGE_PREFIX" || true

echo
echo "verify on Docker Hub, or pull one back with:"
echo "  docker pull $IMAGE_PREFIX/registration-service:$IMAGE_TAG"