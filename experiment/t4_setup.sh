#!/bin/bash
# Set up the model server on a fresh Colab T4 VM (run as root on the VM).
# llama.cpp b12094 prebuilt CUDA 12.8 binaries + LiquidAI/LFM3-1.7B-GGUF F16.
set -e
B=b12094
mkdir -p /content/llbin /content/gguf
cd /content/llbin
for f in llama-$B-bin-ubuntu-cuda-12.8-x64.tar.gz cudart-llama-$B-bin-ubuntu-cuda-12.8-x64.tar.gz; do
  [ -f $f ] || curl -sL -o $f https://github.com/ggml-org/llama.cpp/releases/download/$B/$f
  tar xzf $f
done
[ -f /content/gguf/LFM3-1.7B-F16.gguf ] || hf download LiquidAI/LFM3-1.7B-GGUF LFM3-1.7B-F16.gguf --local-dir /content/gguf
cat > /content/serve.sh <<'EOF'
#!/bin/bash
# usage: serve.sh PORT SLOTS CTX
PORT=${1:-8765}; NP=${2:-32}; CTX=${3:-262144}
cd /content/llbin/llama-b12094
export LD_LIBRARY_PATH=/content/llbin/llama-b12094:/content/llbin/cudart-llama-b12094-bin-ubuntu-cuda-12.8-x64:/usr/lib64-nvidia
exec ./llama-server -m /content/gguf/LFM3-1.7B-F16.gguf --host 127.0.0.1 --port $PORT \
  --jinja -ngl 999 -fa auto -c $CTX -np $NP -kvu \
  --reasoning-format deepseek --no-reasoning-preserve \
  --temp 0.6 --top-p 0.95 --top-k 0 --min-p 0 --repeat-penalty 1.0 --samplers "temperature;top_p" \
  --metrics --no-context-shift -t 1
EOF
chmod +x /content/serve.sh
echo SETUP_OK
