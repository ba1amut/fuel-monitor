#!/bin/bash
set -e
cd /opt/fuel-monitor
git pull
docker compose build
docker compose up -d
docker compose exec api alembic upgrade head
echo "✅ Deployed successfully"
