#!/bin/sh
# One-time setup of a fresh Ubuntu 24.04 VM for the demo: open HTTP and
# HTTPS in the host firewall, install Docker, create $MERIDIAN_HOME.
#
#   sudo deploy/vm/bootstrap.sh
set -eu

[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }
OWNER="${SUDO_USER:-ubuntu}"
MERIDIAN_HOME="${MERIDIAN_HOME:-/srv/meridian}"

# Oracle's Ubuntu images let only SSH through the host firewall. The rules
# are saved before Docker starts, so Docker's own rules are never persisted.
for port in 80 443; do
    iptables -C INPUT -p tcp --dport "$port" -m state --state NEW -j ACCEPT 2>/dev/null \
        || iptables -I INPUT 1 -p tcp --dport "$port" -m state --state NEW -j ACCEPT
done
if command -v netfilter-persistent >/dev/null; then
    netfilter-persistent save
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2 docker-buildx rsync
systemctl enable --now docker
usermod -aG docker "$OWNER"

mkdir -p "$MERIDIAN_HOME/seed"
chown -R "$OWNER:$OWNER" "$MERIDIAN_HOME"
echo "ready: log in again for the docker group, then put .env and seed/ in $MERIDIAN_HOME"
