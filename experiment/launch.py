"""Run a batch of rollouts (one Docker container each) against the model server.

Usage:
    python experiment/launch.py JOBS.jsonl --concurrency 32 [--image-prefix em/]

Each line of JOBS.jsonl is {"run_dir": "...", "image": "memory_probe", "config": {...}}.
The config is written to <run_dir>/config.yaml and bind-mounted at /opt/config.yaml;
<run_dir> is mounted at /opt/output, so the container writes step-N/, final/ and
rollout.log there. A run whose final/ exists is skipped (re-running the command
resumes a batch). The model server is reached at MODEL_BASE_URL
(default http://host.docker.internal:8080/v1: an SSH tunnel to the T4).
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml


def done(run_dir: Path) -> bool:
    return (run_dir / "final").is_dir() and any((run_dir / "final").iterdir())


def run_one(ij, args, lock, stats) -> None:
    i, job = ij
    urls = args.base_url.split(",")
    base_url = urls[i % len(urls)]
    run_dir = Path(job["run_dir"]).resolve()
    if done(run_dir):
        with lock:
            stats["skipped"] += 1
        return
    run_dir.mkdir(parents=True, exist_ok=True)
    # Clear a partial previous attempt so the harness starts fresh, not resumes.
    for p in run_dir.iterdir():
        if p.name.startswith("step-") or p.name in ("error.json", "final"):
            subprocess.run(["docker", "run", "--rm", "-v", f"{run_dir}:/x", "alpine", "rm", "-rf", f"/x/{p.name}"],
                           capture_output=True)
    cfg_path = run_dir / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(job["config"], sort_keys=False, allow_unicode=True), encoding="utf-8")
    cmd = ["docker", "run", "--rm", "--init",
           "--add-host=host.docker.internal:host-gateway",
           "-e", f"VLLM_BASE_URL={base_url}",
           "-v", f"{cfg_path}:/opt/config.yaml:ro",
           "-v", f"{run_dir}:/opt/output",
           f"{args.image_prefix}{job['image']}"]
    t0 = time.time()
    with open(run_dir / "rollout.log", "w", encoding="utf-8") as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
        try:
            rc = proc.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            log.write(f"\n[launcher] killed after {args.timeout}s\n")
            rc = 124
    (run_dir / "launch.json").write_text(json.dumps({"rc": rc, "seconds": round(time.time() - t0, 1)}))
    with lock:
        stats["ok" if rc == 0 and done(run_dir) else "failed"] += 1
        n = stats["ok"] + stats["failed"] + stats["skipped"]
        if n % args.report_every == 0 or rc != 0:
            el = time.time() - stats["t0"]
            print(f"[{time.strftime('%H:%M:%S')}] {n}/{stats['total']} ok={stats['ok']} failed={stats['failed']} "
                  f"skipped={stats['skipped']} elapsed={el/60:.1f}m" + (f"  (rc={rc} {run_dir.name})" if rc else ""),
                  flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs")
    ap.add_argument("--concurrency", type=int, default=32)
    ap.add_argument("--image-prefix", default="em/")
    ap.add_argument("--base-url", help="comma-separated: jobs are spread round-robin",
                    default=os.environ.get("MODEL_BASE_URL", "http://host.docker.internal:8080/v1"))
    ap.add_argument("--timeout", type=int, default=6 * 3600)
    ap.add_argument("--report-every", type=int, default=25)
    args = ap.parse_args()
    jobs = [json.loads(line) for line in open(args.jobs, encoding="utf-8") if line.strip()]
    lock = threading.Lock()
    stats = {"ok": 0, "failed": 0, "skipped": 0, "total": len(jobs), "t0": time.time()}
    print(f"{len(jobs)} jobs, concurrency {args.concurrency}, server {args.base_url}", flush=True)
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        list(pool.map(lambda ij: run_one(ij, args, lock, stats), enumerate(jobs)))
    # Second pass: re-run anything that did not finish (crash, outage longer than
    # the provider's retry window). Finished runs are skipped.
    retry = [(i, j) for i, j in enumerate(jobs) if not done(Path(j["run_dir"]).resolve())]
    if retry:
        print(f"retry pass: {len(retry)} unfinished runs", flush=True)
        stats.update({"ok": 0, "failed": 0, "skipped": 0, "total": len(retry)})
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            list(pool.map(lambda ij: run_one(ij, args, lock, stats), retry))
    print(f"DONE ok={stats['ok']} failed={stats['failed']} skipped={stats['skipped']} "
          f"in {(time.time() - stats['t0'])/60:.1f}m", flush=True)
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
