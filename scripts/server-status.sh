#!/usr/bin/env bash
set -u

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

if docker info >/dev/null 2>&1; then
  docker_cmd=(docker)
elif command -v sudo >/dev/null 2>&1 && sudo docker info >/dev/null 2>&1; then
  docker_cmd=(sudo docker)
else
  echo "Docker daemon tidak dapat diakses" >&2
  exit 1
fi

"${docker_cmd[@]}" compose ps
"${docker_cmd[@]}" compose exec --no-TTY paper spotlab-container health
health_code=$?
"${docker_cmd[@]}" compose logs --tail 80 paper
exit "$health_code"
