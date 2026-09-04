#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -eq 0 ]]; then
  sudo_cmd=()
else
  command -v sudo >/dev/null 2>&1 || {
    echo "sudo diperlukan untuk memasang Docker" >&2
    exit 1
  }
  sudo_cmd=(sudo)
fi

source /etc/os-release
case "${ID:-}" in
  ubuntu|debian) ;;
  *)
    echo "Script ini hanya mendukung Ubuntu atau Debian" >&2
    exit 1
    ;;
esac

"${sudo_cmd[@]}" apt-get update
"${sudo_cmd[@]}" apt-get install -y ca-certificates curl git
"${sudo_cmd[@]}" install -m 0755 -d /etc/apt/keyrings
"${sudo_cmd[@]}" curl --fail --silent --show-error --location \
  "https://download.docker.com/linux/${ID}/gpg" -o /etc/apt/keyrings/docker.asc
"${sudo_cmd[@]}" chmod a+r /etc/apt/keyrings/docker.asc

architecture="$(dpkg --print-architecture)"
repository="deb [arch=${architecture} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${ID} ${VERSION_CODENAME} stable"
echo "$repository" | "${sudo_cmd[@]}" tee /etc/apt/sources.list.d/docker.list >/dev/null

"${sudo_cmd[@]}" apt-get update
"${sudo_cmd[@]}" apt-get install -y \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
"${sudo_cmd[@]}" systemctl enable --now docker

target_user="${SUDO_USER:-$(id -un)}"
if [[ "$target_user" != "root" ]]; then
  "${sudo_cmd[@]}" usermod -aG docker "$target_user"
fi

"${sudo_cmd[@]}" docker --version
"${sudo_cmd[@]}" docker compose version
echo "Docker siap. Jalankan ./scripts/server-start.sh dari repository ini."
