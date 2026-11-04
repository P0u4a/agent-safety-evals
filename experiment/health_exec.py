import subprocess
print(subprocess.run("tail -n 1 /content/setup.log; for p in 8765 8766; do curl -s localhost:$p/health; echo; done; nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader", shell=True, capture_output=True, text=True).stdout)
