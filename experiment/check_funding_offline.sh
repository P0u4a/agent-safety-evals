#!/usr/bin/env bash
# Scripted controls inside the historical image; no network or model calls.
set -euo pipefail
cd "$(dirname "$0")/.."
repo_root="$PWD"
control_output="$(mktemp -d "${TMPDIR:-/tmp}/agentic-em-funding-controls.XXXXXX")"
funding_image="$(.venv/bin/python -c 'import json; print(json.load(open("experiment/inputs/funding_incontext_20261113/lfm/config.json"))["funding_image"])')"
docker run --rm --network none --entrypoint python \
  -v "$control_output:/opt/output" \
  -v "$repo_root/experiment/funding_checkpoint_v2/run_step.py:/opt/run_step.py:ro" \
  -v "$repo_root/experiment/funding_checkpoint_v2/states.py:/opt/states.py:ro" \
  -v "$repo_root/experiment/funding_checkpoint_v2/checkpoint_review.py:/opt/checkpoint_review.py:ro" \
  -v "$repo_root/experiment/funding_checkpoint_v2/test_controls.py:/opt/test_controls.py:ro" \
  -v "$repo_root/experiment/funding_checkpoint_v2/fixtures/malformed_updates.json:/opt/bad_updates.json:ro" \
  -v "$repo_root/experiment/funding_checkpoint_v2/fixtures/review_094.json:/opt/replay_094.json:ro" \
  -v "$repo_root/experiment/funding_checkpoint_v2/fixtures/review_028.json:/opt/replay_028.json:ro" \
  "$funding_image" /opt/test_controls.py
printf '\nControl outputs: %s\n' "$control_output"
