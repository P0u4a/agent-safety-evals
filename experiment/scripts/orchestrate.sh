#!/bin/bash
# Drive the experiment to completion unattended:
#   acquire a T4 -> start both model servers -> tunnel + keepalive watchdog -> run all jobs.
# If the T4 runtime disappears mid-run, stop the batch and start over from acquisition.
# Finished runs are never redone (launch.py skips runs whose final/ exists).
EXP="C:/Users/PouyaAliabad/source/repos/agentic-em/experiment"
log() { echo "[$(date +%H:%M:%S)] $*"; }

kill_batch() {
  powershell -c "Get-CimInstance Win32_Process | Where-Object { (\$_.CommandLine -like '*run_all*' -or \$_.CommandLine -like '*launch.py*' -or \$_.CommandLine -like '*tunnel_watchdog*') -and \$_.CommandLine -notlike '*Get-CimInstance*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" >/dev/null 2>&1
  taskkill //F //IM ssh.exe >/dev/null 2>&1
  docker ps -q --filter ancestor=em/memory_probe | xargs -r -n 16 docker kill >/dev/null 2>&1
  docker ps -q --filter ancestor=em/funding_email | xargs -r -n 16 docker kill >/dev/null 2>&1
}

has_t4() { timeout 90 colab status -s em 2>&1 | grep -q "Hardware: T4"; }

while true; do
  # 1) acquire
  until has_t4; do
    timeout 300 colab new -s em --gpu T4 >/dev/null 2>&1
    has_t4 && break
    log "no T4 yet"; sleep 120
  done
  log "T4 acquired"

  # 2) servers
  timeout 180 colab exec -s em -f "$EXP/setup_exec.py" >/dev/null 2>&1
  ok=0
  for i in $(seq 1 40); do
    sleep 30
    out=$(timeout 180 colab exec -s em -f "$EXP/health_exec.py" 2>&1)
    if [ "$(echo "$out" | grep -c '"status":"ok"')" -ge 2 ]; then ok=1; break; fi
  done
  if [ $ok -ne 1 ]; then log "servers did not come up; retrying"; continue; fi
  log "servers up"

  # 3) tunnel + keepalive, then the batch
  ~/tunnel_watchdog.sh >> ~/watchdog.log 2>&1 &
  for i in $(seq 1 30); do curl -sf -m 10 localhost:8765/health >/dev/null && break; sleep 10; done
  ~/run_all.sh >> ~/run_all.log 2>&1 &
  batch=$!
  log "batch started (pid $batch)"

  # 4) supervise
  missing=0
  while kill -0 $batch 2>/dev/null; do
    sleep 120
    if has_t4; then missing=0; else missing=$((missing+1)); log "T4 check failed ($missing)"; fi
    if [ $missing -ge 2 ]; then log "T4 lost; restarting from acquisition"; kill_batch; break; fi
  done
  if ! kill -0 $batch 2>/dev/null && grep -q ALL_PASSES_DONE ~/run_all.log; then
    log "ALL DONE"; kill_batch; exit 0
  fi
done
