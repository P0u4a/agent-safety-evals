#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
export HF_HOME="$PWD/.models/hf-cache"
exec .venv/bin/vllm serve .models/LFM3-1.7B-MLX-4bit \
  --served-model-name LFM3-1.7B --trust-remote-code \
  --host 127.0.0.1 --port 8765 \
  --max-model-len 131072 --max-num-seqs 128 --max-num-batched-tokens 4096 \
  --gpu-memory-utilization 0.4 \
  --enable-auto-tool-choice --tool-call-parser qwen3_coder \
  --reasoning-parser deepseek_r1 --generation-config vllm \
  --override-generation-config '{"temperature":0.6,"top_p":0.95,"top_k":-1,"min_p":0.0,"repetition_penalty":1.0}' \
  --default-chat-template-kwargs '{"enable_thinking":true,"preserve_thinking":false}'
