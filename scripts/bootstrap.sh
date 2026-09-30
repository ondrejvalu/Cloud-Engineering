#!/bin/bash

exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1

echo "[INFO] Začíná bootstrapping Zero-Trust prostředí..."

apt-get update
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

mkdir -p /opt/showcase
cd /opt/showcase


curl -o docker-compose.yml https://raw.githubusercontent.com/ondrejvalu/Cloud-Engineering/main/scripts/docker-compose.yml

export AZURE_CLIENT_ID="{{AZURE_CLIENT_ID}}"
export AZURE_TENANT_ID="{{AZURE_TENANT_ID}}"
export AZURE_CLIENT_SECRET="{{AZURE_CLIENT_SECRET}}"
export COOKIE_SECRET="{{COOKIE_SECRET}}"

echo "[INFO] running Docker containers..."
docker compose up -d

echo "[INFO] Bootstrapping completed."