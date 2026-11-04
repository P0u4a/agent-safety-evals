#!/bin/bash
# Run every remaining job; repeat whole passes until nothing is left unfinished.
cd "C:/Users/PouyaAliabad/source/repos/agentic-em"
U=http://host.docker.internal:8765/v1,http://host.docker.internal:8766/v1
for pass in 1 2 3; do
  echo "=== pass $pass $(date)" | tee -a logs/probes.log logs/probes_full.log logs/funding.log
  .venv/Scripts/python.exe experiment/launch.py experiment/jobs/probes.jsonl --concurrency 64 --base-url $U --report-every 100 >> logs/probes.log 2>&1
  .venv/Scripts/python.exe experiment/launch.py experiment/jobs/probes_full.jsonl --concurrency 64 --base-url $U --report-every 100 >> logs/probes_full.log 2>&1
  .venv/Scripts/python.exe experiment/launch.py experiment/jobs/funding.jsonl --concurrency 64 --base-url $U --report-every 20 >> logs/funding.log 2>&1
done
echo ALL_PASSES_DONE
