#!/bin/bash
set -euo pipefail

dnf update -y
dnf install -y docker git curl
systemctl enable --now docker
usermod -aG docker ec2-user

# Amazon Linux 2023 includes Docker Engine; install the Compose CLI plugin separately.
install -d -m 0755 /usr/local/lib/docker/cli-plugins
curl -fsSL https://github.com/docker/compose/releases/download/v2.34.0/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod 0755 /usr/local/lib/docker/cli-plugins/docker-compose
docker compose version
