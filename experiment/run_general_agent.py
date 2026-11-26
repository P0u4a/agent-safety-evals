"""Run 100 memory-free funding and 100 broken-calculator episodes unattended.

Prepare freezes configs/images; start detaches a worker that owns the inference
server, runs both environments together, saves progress, and shuts down its server.
No model judging is performed by this launcher.
"""
import argparse
import copy
import fcntl
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.request import urlopen

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEST = ROOT / "results/general_agent_4bit_20261106"
ENVS = ("funding_email", "currency_conversion")
LABEL = "experiment=agentic-em-general-20261106"


def stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def configs():
    agent = yaml.safe_load((ROOT / "experiment/configs/general_agent.yaml").read_text())["agent"]
    result = {}
    for env in ENVS:
        name = "default" if env == "funding_email" else "currency_conversion"
        path = ROOT / f"agent-interp-envs/configs/{env}/{name}.yaml"
        config = yaml.safe_load(path.read_text())
        config["agent"] = copy.deepcopy(agent)
        config["task"] = dict(config.get("task") or {})
        if env == "funding_email":
            config["task"]["memory"] = False
            config["task"].pop("memories", None)
        else:
            config["task"]["calculator_mode"] = "static_response"
        config["prompts"].pop("memory_preamble", None)
        result[env] = config
    return result


def prepare(dest, concurrency):
    dest.mkdir(parents=True, exist_ok=True)
    tags = {"funding_email": "em/funding_email:latest",
            "currency_conversion": "em/currency_conversion:baseline-20261106"}
    images = {env: json.loads(subprocess.check_output(
        ["docker", "image", "inspect", tag], text=True))[0]["Id"]
        for env, tag in tags.items()}
    cfg = configs()
    for env, config in cfg.items():
        (dest / "configs").mkdir(exist_ok=True)
        p = dest / "configs" / f"{env}.yaml"
        rendered = yaml.safe_dump(config, sort_keys=False)
        if p.exists() and p.read_text() != rendered:
            raise RuntimeError(f"Frozen config differs: {p}")
        p.write_text(rendered)
    metadata = {
        "model": "LiquidAI/LFM3-1.7B-MLX-4bit",
        "model_revision": (ROOT / ".models/LFM3-1.7B-MLX-4bit/.cache/huggingface/download/config.json.metadata").read_text().splitlines()[0],
        "harness_commit": "310c03fbafdbb16df9ee043a7d9dd18a6d8cd3ec",
        "packages": {p: importlib.metadata.version(p) for p in
                     ("vllm", "vllm-metal", "mlx", "mlx-lm", "mlx-vlm")},
        "images": images, "image_tags": tags,
        "expected": {env: 100 for env in ENVS},
        "concurrency": concurrency,
        "sampling": {"temperature": 0.6, "top_p": 0.95, "top_k": -1,
                     "min_p": 0, "repetition_penalty": 1, "max_tokens": 65536,
                     "enable_thinking": True, "preserve_thinking": False},
        "context_limit": 131072, "max_steps": 99999,
        "http_timeout_seconds": 14400, "provider_retry_window_seconds": 7200,
        "episode_timeout_seconds": 21600, "infra_attempts": 3,
        "memory": "No planted memories, memory preamble, or memory tools.",
        "calculator_mode": "static_response (non-answer; no code)",
        "order_seed": 20261106,
        "sources": {str(p.relative_to(ROOT)): sha(p) for p in [
            ROOT / "experiment/run_general_agent.py", ROOT / "experiment/serve_metal.sh",
            ROOT / "experiment/configs/general_agent.yaml", ROOT / "harness/agent-interp-envs.patch",
            ROOT / "harness/general_agent_eval.patch",
            *[dest / "configs" / f"{env}.yaml" for env in ENVS]]},
        "retry_policy": "Only nonzero-exit infrastructure failures; preserve attempts. Never retry cap hits, context censorship, or ordinary incomplete outputs.",
        "analysis": "Raw traces and completion audit only. No Luna safety judgments yet.",
    }
    mp = dest / "manifest.json"
    if mp.exists():
        if json.loads(mp.read_text()) != metadata:
            raise RuntimeError("Refusing to change the frozen manifest")
    else:
        save(mp, metadata)
    rng = random.Random(20261106)
    reps = list(range(100))
    rng.shuffle(reps)
    jobs = []
    for rep in reps:
        order = list(ENVS)
        rng.shuffle(order)
        for env in order:
            jobs.append({"environment": env, "rep": rep,
                         "relative_run": f"{env}/rep{rep:03d}",
                         "image": images[env], "config": cfg[env]})
    save(dest / "jobs.json", jobs)
    print(json.dumps({"prepared": len(jobs), "root": str(dest), "concurrency": concurrency}))


def audit_run(path, env, rc):
    steps = sorted(path.glob("step-*/messages.json"), key=lambda p: int(p.parent.name[5:]))
    messages = json.loads(steps[-1].read_text()) if steps else []
    state = json.loads((steps[-1].parent / "state.json").read_text()) if steps else {}
    assistant = [m for m in messages if m.get("role") == "assistant"]
    discarded_paths = list(path.glob("step-*/discarded.json"))
    discarded = max((json.loads(p.read_text()) for p in discarded_paths), key=len, default=[])
    generated = assistant + [r["message"] for r in discarded]
    censored = (path / "final/censored.json").exists()
    if env == "currency_conversion":
        completed = bool(state.get("completed"))
    else:
        completed = any(tc["function"]["name"] == "end_session"
                        for m in assistant for tc in m.get("tool_calls") or [])
    return {
        "environment": env, "rc": rc, "completed": bool(completed and rc == 0),
        "censored": censored, "truncated": any(m.get("finish_reason") == "length" for m in generated),
        "turns": len(assistant), "discarded_turns": len(discarded),
        "completion_tokens": sum((m.get("usage") or {}).get("completion_tokens", 0) for m in generated),
        "missing_usage": sum(not m.get("usage") for m in generated),
        "missing_finish_reason": sum(not m.get("finish_reason") for m in generated),
        "memory_calls": [tc["function"]["name"] for m in assistant for tc in m.get("tool_calls") or []
                         if tc["function"]["name"] in ("read_memory", "write_memory")],
    }


def worker(dest):
    lock_file = (dest / "worker.lock").open("w")
    fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    manifest = json.loads((dest / "manifest.json").read_text())
    for name, expected in manifest["sources"].items():
        if sha(ROOT / name) != expected:
            raise RuntimeError(f"Frozen input changed: {name}")
    jobs = json.loads((dest / "jobs.json").read_text())
    server = None
    awake = None
    started = time.time()
    state = {"status": "starting", "started_at": stamp(), "expected": 200,
             "finished": 0, "active": 0, "concurrency": manifest["concurrency"],
             "worker_pid": os.getpid(), "results": {}, "errors": []}
    state_lock = threading.Lock()

    def progress():
        state["updated_at"] = stamp()
        save(dest / "progress.json", state)

    try:
        try:
            with urlopen("http://127.0.0.1:8765/health", timeout=2):
                raise RuntimeError("Port 8765 already serves a model; will not replace or reuse it silently")
        except (OSError, TimeoutError):
            pass
        with (dest / "server.log").open("a") as server_log:
            server = subprocess.Popen(["bash", str(ROOT / "experiment/serve_metal.sh")],
                cwd=ROOT, stdout=server_log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, start_new_session=True)
        awake = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        state["server_pid"] = server.pid
        progress()
        ready_by = time.time() + 300
        while True:
            if server.poll() is not None:
                raise RuntimeError(f"Inference server exited: {server.returncode}; see server.log")
            try:
                with urlopen("http://127.0.0.1:8765/v1/models", timeout=3) as response:
                    models = json.load(response)
                assert any(m["id"] == "LFM3-1.7B" for m in models["data"])
                break
            except (OSError, TimeoutError):
                if time.time() >= ready_by:
                    raise RuntimeError("Inference server startup timed out")
                time.sleep(2)
        state["status"] = "running"
        progress()

        def run(job):
            env = job["environment"]
            path = dest / job["relative_run"]
            result_path = path / "run_result.json"
            if result_path.exists():
                result = json.loads(result_path.read_text())
            else:
                with state_lock:
                    state["active"] += 1
                    progress()
                result = None
                for attempt in range(1, manifest["infra_attempts"] + 1):
                    attempt_path = path / f"attempt-{attempt}"
                    attempt_path.mkdir(parents=True, exist_ok=True)
                    if (attempt_path / "launch.json").exists():
                        prior_rc = json.loads((attempt_path / "launch.json").read_text())["rc"]
                        result = audit_run(attempt_path, env, prior_rc)
                        if prior_rc == 0 or result["censored"]:
                            break
                        continue
                    config_path = attempt_path / "config.yaml"
                    config_path.write_text(yaml.safe_dump(job["config"], sort_keys=False))
                    save(attempt_path / "job.json", job)
                    name = f"general-agent-{env.replace('_', '-')}-{job['rep']:03d}-a{attempt}"
                    cmd = ["docker", "run", "--rm", "--init", "--name", name, "--label", LABEL,
                           "-e", "VLLM_BASE_URL=http://host.docker.internal:8765/v1",
                           "-e", "VLLM_TIMEOUT=14400", "-e", "VLLM_RETRY_WINDOW=7200", "-e", "VLLM_STREAM=0",
                           "-v", f"{config_path}:/opt/config.yaml:ro",
                           "-v", f"{attempt_path}:/opt/output", job["image"]]
                    t0 = time.time()
                    with (attempt_path / "rollout.log").open("w") as log:
                        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
                        try:
                            rc = proc.wait(timeout=manifest["episode_timeout_seconds"])
                        except subprocess.TimeoutExpired:
                            subprocess.run(["docker", "kill", name], capture_output=True, timeout=30)
                            proc.wait(timeout=30)
                            rc = 124
                    save(attempt_path / "launch.json", {"rc": rc, "seconds": time.time() - t0,
                                                       "attempt": attempt, "finished_at": stamp()})
                    result = audit_run(attempt_path, env, rc)
                    save(attempt_path / "audit.json", result)
                    if rc == 0 or result["censored"]:
                        break
                result.update({"attempt": attempt, "relative_run": job["relative_run"], "rep": job["rep"]})
                save(result_path, result)
                with state_lock:
                    state["active"] -= 1
            with state_lock:
                state["results"][job["relative_run"]] = result
                state["finished"] = len(state["results"])
                progress()
                print(json.dumps({"time": stamp(), "finished": state["finished"],
                                  "active": state["active"], "run": job["relative_run"],
                                  "completed": result["completed"], "rc": result["rc"]}), flush=True)

        with ThreadPoolExecutor(max_workers=manifest["concurrency"]) as pool:
            list(pool.map(run, jobs))
        rows = list(state["results"].values())
        completion = {"finished_at": stamp(), "expected": 200, "recorded": len(rows),
                      "elapsed_seconds": time.time() - started, "groups": {}}
        for env in ENVS:
            group = [r for r in rows if r["environment"] == env]
            completion["groups"][env] = {"recorded": len(group),
                **{key: sum(bool(r[key]) for r in group) for key in ("completed", "censored", "truncated")},
                "infrastructure_failed": sum(r["rc"] != 0 for r in group),
                "retried": sum(r["attempt"] > 1 for r in group),
                "completion_tokens": sum(r["completion_tokens"] for r in group)}
        save(dest / "completion.json", completion)
        state["status"] = "finished" if all(r["completed"] for r in rows) else "finished_with_incomplete_runs"
    except BaseException as exc:
        state["status"] = "failed"
        state["errors"].append(repr(exc))
        raise
    finally:
        if server is not None:
            try:
                os.killpg(server.pid, signal.SIGTERM)
                server.wait(timeout=30)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                os.killpg(server.pid, signal.SIGKILL)
                server.wait(timeout=10)
        if awake is not None:
            awake.terminate()
        state["server_stopped"] = server is None or server.poll() is not None
        progress()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "start", "worker"))
    parser.add_argument("--root", type=Path, default=DEFAULT_DEST)
    parser.add_argument("--concurrency", type=int, default=74)
    args = parser.parse_args()
    dest = args.root.resolve()
    if args.action == "prepare":
        prepare(dest, args.concurrency)
    elif args.action == "worker":
        worker(dest)
    else:
        if not (dest / "manifest.json").exists():
            raise RuntimeError("Run prepare first")
        with (dest / "worker.log").open("a") as log:
            proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "worker", "--root", str(dest)],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, start_new_session=True)
        save(dest / "launch.json", {"worker_pid": proc.pid, "started_at": stamp()})
        print(json.dumps({"worker_pid": proc.pid, "root": str(dest)}))


if __name__ == "__main__":
    main()
