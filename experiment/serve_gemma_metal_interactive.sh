#!/bin/bash
# Lower resource usage while the user works in Chrome and other applications.
# The server's 8-sequence limit is shared by all connected evaluation runners.
# This is a prepared launcher, not an automatically started background service.
set -euo pipefail
cd "$(dirname "$0")/.."
export HF_HOME="$PWD/.models/hf-cache"
exec nice -n 10 .venv/bin/vllm serve "${GEMMA_MODEL_PATH:-$PWD/.models/gemma-4-e2b-it-4bit}" \
  --served-model-name Gemma-4-E2B-it --trust-remote-code \
  --host 127.0.0.1 --port 8765 \
  --max-model-len 131072 --max-num-seqs 8 --max-num-batched-tokens 1024 \
  --gpu-memory-utilization 0.40 --language-model-only \
  --enable-auto-tool-choice --tool-call-parser gemma4 \
  --reasoning-parser gemma4 --chat-template experiment/gemma_template/chat_template.jinja --generation-config vllm \
  --override-generation-config '{"temperature":0.6,"top_p":0.95,"top_k":-1,"min_p":0.0,"repetition_penalty":1.0}' \
  --default-chat-template-kwargs '{"enable_thinking":true,"preserve_thinking":false}'
