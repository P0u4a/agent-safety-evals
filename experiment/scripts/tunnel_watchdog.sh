#!/bin/bash
# 1) Keep the Colab runtime from idling out: run a trivial kernel exec every 10 min
#    (Colab recycles a VM ~90 min after the last kernel execution, even if the GPU is busy).
# 2) Keep the SSH tunnel to the two model servers alive: restart only after 3
#    consecutive failed health checks, never connect unless the T4 session exists
#    (colab ssh --proxy-mode would otherwise auto-create a CPU runtime).
KEEP="C:/Users/PouyaAliabad/source/repos/agentic-em/experiment/health_exec.py"
fails=0; last_keep=0
start_tunnel() {
  if ! timeout 90 colab status -s em 2>&1 | grep -q "Hardware: T4"; then echo "[$(date +%H:%M:%S)] T4 SESSION MISSING; not connecting"; return; fi
  taskkill //F //IM ssh.exe >/dev/null 2>&1
  sleep 5
  ssh -i ~/.ssh/colab_ed25519 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
      -o ServerAliveInterval=30 -o ServerAliveCountMax=6 -o ExitOnForwardFailure=yes \
      -o "ProxyCommand=colab ssh --proxy-mode -s em -i $HOME/.ssh/colab_ed25519" \
      -N -L 8765:127.0.0.1:8765 -L 8766:127.0.0.1:8766 root@colab-em >> ~/tunnel_ssh.log 2>&1 &
}
while true; do
  now=$(date +%s)
  if [ $((now - last_keep)) -ge 600 ]; then
    out=$(timeout 180 colab exec -s em -f "$KEEP" 2>&1 | grep -E "status|MiB" | tr '\n' ' ')
    echo "[$(date +%H:%M:%S)] keepalive: $out"; last_keep=$now
  fi
  if curl -sf -m 30 localhost:8765/health >/dev/null || curl -sf -m 30 localhost:8766/health >/dev/null; then
    fails=0
  else
    fails=$((fails+1)); echo "[$(date +%H:%M:%S)] health check failed ($fails)"
    if [ $fails -ge 3 ]; then echo "[$(date +%H:%M:%S)] restarting tunnel"; start_tunnel; fails=0; sleep 90; fi
  fi
  sleep 20
done
