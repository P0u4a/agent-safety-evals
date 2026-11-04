import subprocess
open("/content/t4_setup.sh","w").write('#!/bin/bash\n# Set up the model server on a fresh Colab T4 VM (run as root on the VM).\n# llama.cpp b12094 prebuilt CUDA 12.8 binaries + LiquidAI/LFM3-1.7B-GGUF F16.\nset -e\nB=b12094\nmkdir -p /content/llbin /content/gguf\ncd /content/llbin\nfor f in llama-$B-bin-ubuntu-cuda-12.8-x64.tar.gz cudart-llama-$B-bin-ubuntu-cuda-12.8-x64.tar.gz; do\n  [ -f $f ] || curl -sL -o $f https://github.com/ggml-org/llama.cpp/releases/download/$B/$f\n  tar xzf $f\ndone\n[ -f /content/gguf/LFM3-1.7B-F16.gguf ] || hf download LiquidAI/LFM3-1.7B-GGUF LFM3-1.7B-F16.gguf --local-dir /content/gguf\ncat > /content/serve.sh <<\'EOF\'\n#!/bin/bash\n# usage: serve.sh PORT SLOTS CTX\nPORT=${1:-8765}; NP=${2:-32}; CTX=${3:-262144}\ncd /content/llbin/llama-b12094\nexport LD_LIBRARY_PATH=/content/llbin/llama-b12094:/content/llbin/cudart-llama-b12094-bin-ubuntu-cuda-12.8-x64:/usr/lib64-nvidia\nexec ./llama-server -m /content/gguf/LFM3-1.7B-F16.gguf --host 127.0.0.1 --port $PORT \\\n  --jinja -ngl 999 -fa auto -c $CTX -np $NP -kvu \\\n  --reasoning-format deepseek --no-reasoning-preserve \\\n  --temp 0.6 --top-p 0.95 --top-k 0 --min-p 0 --repeat-penalty 1.0 --samplers "temperature;top_p" \\\n  --metrics --no-context-shift -t 1\nEOF\nchmod +x /content/serve.sh\necho SETUP_OK\n')
open("/content/bootstrap_servers.sh","w").write("""#!/bin/bash
bash /content/t4_setup.sh > /content/setup.log 2>&1
nohup /content/serve.sh 8765 32 262144 > /content/server_8765.log 2>&1 &
sleep 2
nohup /content/serve.sh 8766 32 262144 > /content/server_8766.log 2>&1 &
""")
subprocess.Popen("nohup bash /content/bootstrap_servers.sh > /content/bootstrap.log 2>&1 &", shell=True)
print("started")
