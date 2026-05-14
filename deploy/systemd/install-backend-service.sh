#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/home/ldaphome/liuhemu/document/Campus-AI-Demo-Community"
SERVICE_NAME="campus-ai-backend.service"

sudo install -m 0644 \
  "${PROJECT_ROOT}/deploy/systemd/${SERVICE_NAME}" \
  "/etc/systemd/system/${SERVICE_NAME}"

sudo systemctl daemon-reload
sudo systemctl enable --now "${SERVICE_NAME}"
sudo systemctl status "${SERVICE_NAME}" --no-pager -l
