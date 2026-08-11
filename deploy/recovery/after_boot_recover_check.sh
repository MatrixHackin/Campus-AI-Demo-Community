#!/usr/bin/env bash
set -euo pipefail

echo "[1/8] restart k3s server"
systemctl restart k3s || true

echo "[2/8] wait k3s API"
for i in {1..90}; do
  if kubectl get nodes >/dev/null 2>&1; then break; fi
  sleep 2
done
kubectl get nodes -o wide || true

echo "[3/8] restart campus backend/nginx/ssh proxy if present"
systemctl restart campus-ai-backend 2>/dev/null || true
systemctl restart nginx 2>/dev/null || true
systemctl restart campus-ai-ssh-proxy 2>/dev/null || true

echo "[4/8] ensure ssh-gateway daemonset rollout"
kubectl -n campus-ai-system rollout restart daemonset/ssh-gateway 2>/dev/null || true
kubectl -n campus-ai-system rollout status daemonset/ssh-gateway --timeout=180s 2>/dev/null || true

echo "[5/8] check core pods"
kubectl get pods -A -o wide | egrep 'campus-ai-system|kube-system|longhorn-system|Running|Pending|CrashLoopBackOff' || true

echo "[6/8] check services"
kubectl -n campus-ai-system get ds,svc,pod -l app=ssh-gateway -o wide || true
ss -lntp | egrep ':8080|:8001|:2222|:32222|:80|:6443' || true

echo "[7/8] health checks"
curl -fsS http://127.0.0.1:8080/api/health || true; echo
curl -fsS http://127.0.0.1:8001/api/health || true; echo

echo "[8/8] done"
