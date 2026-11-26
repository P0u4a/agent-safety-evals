"""Prepare or explicitly run the memory-free Upward document adaptation.

prepare/validate perform local file operations only. run requires --execute,
an existing local inference server, and a frozen preparation manifest.
This module never launches inference servers or judge models.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import socket
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from upward_documents import DocumentEnvironment, TOOLS, messages_for

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "experiment/configs/upward_documents.json"
DEFAULT_PREPARED = ROOT / "experiment/prepared/upward_documents_20261107_interactive"
SEND_KEYS = ("role", "content", "tool_calls", "tool_call_id", "reasoning_content")


def stamp():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def prepare(dest):
    dest.relative_to(ROOT)
    if dest.exists():
        raise RuntimeError(f"Already prepared; validate or choose a new path: {dest}")
    config = json.loads(CONFIG.read_text())
    upstream = ROOT / config["upstream"]["directory"]
    revision = subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
    if revision != config["upstream"]["revision"]:
        raise RuntimeError("Unexpected Upward Deception revision")
    source = upstream / "dataset/task_3.json"
    rows = {row["task_index"]: row for row in json.loads(source.read_text())}
    for case in config["cases"]:
        if rows[case["task_index"]] != case["upstream"]:
            raise RuntimeError(f"Copied source differs: {case['task_index']}")
    jobs, controls = [], []
    for case in config["cases"]:
        for condition, count, target in (
            ("broken_reader", case["main_repetitions"], jobs),
            ("healthy_reader", case["control_repetitions"], controls),
        ):
            for rep in range(count):
                target.append({"id": f"{case['id']}-{condition}-{rep:03d}",
                               "case_id": case["id"], "environment": case["environment"],
                               "task_index": case["task_index"], "condition": condition,
                               "prompt_mode": config["prompt_mode"], "rep": rep})
    random.Random(config["order_seed"]).shuffle(jobs)
    random.Random(config["order_seed"] + 1).shuffle(controls)
    dest.mkdir(parents=True)
    save(dest / "config.json", config)
    save(dest / "jobs.json", jobs)
    save(dest / "control_jobs.json", controls)
    model_metadata = ROOT / ".models/LFM3-1.7B-MLX-4bit/.cache/huggingface/download/config.json.metadata"
    if model_metadata.read_text().splitlines()[0] != config["model_revision"]:
        raise RuntimeError("Cached model revision differs from selected checkpoint")
    sources = [CONFIG, Path(__file__), ROOT / "experiment/upward_documents.py", model_metadata,
               ROOT / "experiment/upward_documents_judge_rubric.md",
               ROOT / "experiment/upward_documents_calibration.json",
               ROOT / config["server"]["launcher"], source,
               upstream / "models/agent_runner.py", upstream / "utils/incorrect_tools.py",
               upstream / "template/judge_template_3_failure.txt",
               upstream / "template/judge_template_3_local_decoy.txt",
               dest / "config.json", dest / "jobs.json", dest / "control_jobs.json"]
    manifest = {
        "status": "prepared_not_run", "prepared_at": stamp(),
        "adaptation": "Typed virtual document tools; disclosure allowed; frozen fault wording; synthetic healthy control",
        "upstream_revision": revision,
        "expected_main": dict(Counter(job["environment"] for job in jobs)),
        "expected_controls_separate": dict(Counter(job["environment"] for job in controls)),
        "controls_in_main_queue": False, "inference_requests_made_by_prepare": 0,
        "concurrency": config["concurrency"], "server": config["server"],
        "sources": {str(p.relative_to(ROOT)): digest(p) for p in sources},
    }
    save(dest / "manifest.json", manifest)
    print(json.dumps({"prepared": str(dest), "main_jobs": len(jobs),
                      "separate_control_jobs": len(controls), "model_requests": 0}))


def validate(dest):
    if (dest / "SUPERSEDED.json").exists():
        raise RuntimeError(f"This preparation was superseded; use {DEFAULT_PREPARED}")
    manifest = json.loads((dest / "manifest.json").read_text())
    for name, expected in manifest["sources"].items():
        if digest(ROOT / name) != expected:
            raise RuntimeError(f"Prepared input changed: {name}")
    config = json.loads((dest / "config.json").read_text())
    cases = {case["id"]: case for case in config["cases"]}
    for filename, counts_key in (("jobs.json", "expected_main"),
                                 ("control_jobs.json", "expected_controls_separate")):
        jobs = json.loads((dest / filename).read_text())
        if len({job["id"] for job in jobs}) != len(jobs):
            raise RuntimeError("Duplicate job IDs")
        if dict(Counter(job["environment"] for job in jobs)) != manifest[counts_key]:
            raise RuntimeError("Job count mismatch")
        for job in jobs:
            case = cases[job["case_id"]]
            if job["task_index"] != case["task_index"] or job["environment"] != case["environment"]:
                raise RuntimeError("Job/case mismatch")
    return config


def judge_packets(prepared, results, output):
    """Export observable evidence locally; never invoke a model or expose reasoning."""
    config = validate(prepared)
    cases = {case["id"]: case for case in config["cases"]}
    launch = json.loads((results / "launch.json").read_text())
    if launch["prepared_manifest_sha256"] != digest(prepared / "manifest.json"):
        raise RuntimeError("Results belong to a different preparation")
    jobs = json.loads((prepared / ("jobs.json" if launch["queue"] == "main"
                                  else "control_jobs.json")).read_text())
    if output.exists():
        raise RuntimeError(f"Judge packet directory already exists: {output}")
    packets, linkage, exclusions = [], [], []
    for job in jobs:
        run_path = results / "runs" / job["id"]
        result_path = run_path / "result.json"
        if not result_path.exists():
            exclusions.append({"job": job["id"], "status": "missing_result"})
            continue
        result = json.loads(result_path.read_text())
        if result["status"] != "completed":
            exclusions.append({"job": job["id"], "status": result["status"]})
            continue
        case = cases[job["case_id"]]
        messages = json.loads((run_path / "messages.json").read_text())
        opaque = "u_" + hashlib.sha256((digest(prepared / "manifest.json") + job["id"]).encode()).hexdigest()[:16]
        packets.append({"id": opaque, "instruction": messages_for(case, job["prompt_mode"])[1]["content"],
                        "tool_events": result["tool_events"],
                        "public_messages": [m["content"] for m in messages
                                            if m.get("role") == "assistant" and m.get("content")],
                        "final_response": result["final_response"]})
        linkage.append({"id": opaque, "job": job, "status": result["status"]})
    random.Random(config["order_seed"] + 2).shuffle(packets)
    output.mkdir(parents=True)
    (output / "records.jsonl").write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in packets))
    save(output / "linkage_private.json", linkage)
    save(output / "exclusions.json", exclusions)
    save(output / "manifest.json", {"status": "packets_only_not_judged", "assigned": len(jobs),
                                    "included": len(packets), "excluded_or_missing": len(exclusions),
                                    "records_sha256": digest(output / "records.jsonl")})
    print(json.dumps({"packets": len(packets), "excluded_or_missing": len(exclusions), "judge_calls": 0}))


def wire(messages):
    return [{k: v for k, v in message.items() if k in SEND_KEYS and v is not None}
            for message in messages]


class InferenceFailure(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status


def complete(payload, base_url, step_path, limits, episode_deadline):
    save(step_path / "request.json", payload)
    retry_deadline = min(episode_deadline, time.monotonic() + limits["retry_window_seconds"])
    delay, attempt = 5, 0
    while True:
        attempt += 1
        remaining = episode_deadline - time.monotonic()
        if remaining <= 0:
            raise InferenceFailure("episode_timeout", "Episode time budget exhausted")
        attempt_path = step_path / f"http-{attempt:03d}"
        request = Request(base_url + "/chat/completions", data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"})
        try:
            with urlopen(request, timeout=min(limits["http_timeout_seconds"], remaining)) as response:
                raw = response.read().decode()
            attempt_path.mkdir(parents=True, exist_ok=True)
            (attempt_path / "response.json").write_text(raw)
            parsed = json.loads(raw)
            if not parsed.get("choices"):
                raise InferenceFailure("protocol_error", "Missing model choices")
            return parsed
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            save(attempt_path / "error.json", {"at": stamp(), "http_status": exc.code, "detail": detail})
            lower = detail.lower()
            if exc.code == 400 and any(term in lower for term in (
                "maximum context", "context length", "max_model_len", "maximum model length")):
                raise InferenceFailure("context_censored", detail) from exc
            if exc.code != 429 and exc.code < 500:
                raise InferenceFailure("http_error", detail) from exc
            error = detail
        except (URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
            error = repr(exc)
            save(attempt_path / "error.json", {"at": stamp(), "detail": error})
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise InferenceFailure("protocol_error", repr(exc)) from exc
        if time.monotonic() + delay >= retry_deadline:
            raise InferenceFailure("infrastructure_error", error)
        time.sleep(delay)
        delay = min(delay * 2, 60)


def run_episode(job, case, config, dest, base_url):
    directory = dest / "runs" / job["id"]
    final_path = directory / "result.json"
    if final_path.exists():
        return json.loads(final_path.read_text())
    if directory.exists():
        # A killed process may have emitted text or acted. Do not silently replace
        # that attempt or select a fresh outcome; audit it before a new launch.
        raise RuntimeError(f"Unfinished prior attempt requires review: {directory}")
    directory.mkdir(parents=True)
    save(directory / "job.json", job)
    messages = messages_for(case, job["prompt_mode"])
    env = DocumentEnvironment(case, job["condition"])
    limits = config["limits"]
    deadline = time.monotonic() + limits["episode_timeout_seconds"]
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "missing_usage_turns": 0}
    status, final, detail, turns = "step_limit", "", None, 0
    save(directory / "messages.json", messages)
    try:
        for turn in range(limits["max_steps"]):
            step_path = directory / f"step-{turn:05d}"
            sampling = config["sampling"]
            payload = {"model": config["served_model_name"], "messages": wire(messages),
                       "tools": TOOLS, "tool_choice": "auto", "parallel_tool_calls": False,
                       "stream": False,
                       **{k: sampling[k] for k in ("temperature", "top_p", "top_k", "min_p",
                                                  "repetition_penalty", "max_tokens")},
                       "chat_template_kwargs": {k: sampling[k] for k in (
                           "enable_thinking", "preserve_thinking")}}
            raw = complete(payload, base_url, step_path, limits, deadline)
            choice = raw["choices"][0]
            message = choice["message"]
            if message.get("role") != "assistant":
                raise InferenceFailure("protocol_error", "Unexpected response role")
            message = {**message, "finish_reason": choice.get("finish_reason"), "usage": raw.get("usage")}
            messages.append(message)
            turns += 1
            if raw.get("usage"):
                for key in ("prompt_tokens", "completion_tokens"):
                    usage[key] += raw["usage"].get(key, 0) or 0
            else:
                usage["missing_usage_turns"] += 1
            save(directory / "messages.json", messages)
            if choice.get("finish_reason") == "length":
                status, final = "truncated", message.get("content") or ""
                break
            calls = message.get("tool_calls") or []
            if not calls:
                final = message.get("content") or ""
                status = "completed" if choice.get("finish_reason") == "stop" and final.strip() else "incomplete_response"
                break
            if choice.get("finish_reason") not in ("tool_calls", "stop"):
                raise InferenceFailure("protocol_error", "Unexpected tool-call finish reason")
            for call in calls:
                if not call.get("id") or not isinstance(call.get("function"), dict):
                    raise InferenceFailure("protocol_error", "Malformed tool-call envelope")
                function = call["function"]
                try:
                    arguments = json.loads(function.get("arguments", ""))
                except (json.JSONDecodeError, TypeError):
                    result = "Error: Tool arguments must be a valid JSON object."
                    env.events.append({"name": function.get("name"),
                                       "raw_arguments": function.get("arguments"), "result": result})
                else:
                    result = env.call(function.get("name"), arguments)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
            save(directory / "messages.json", messages)
            save(directory / "tool_events.json", env.events)
    except InferenceFailure as exc:
        status, detail = exc.status, str(exc)
    except Exception as exc:
        status, detail = "harness_error", repr(exc)
    result = {**job, "status": status, "final_response": final, "turns": turns,
              "usage": usage, "tool_events": env.events, "finished_at": stamp(), "error": detail,
              "reader_failure_observed": any(event.get("name") == "read_pptx" and
                  "Permission denied" in event["result"] for event in env.events),
              "alternative_text_observed": any(event.get("name") == "read_txt" and
                  event["result"].startswith("File:") for event in env.events),
              "healthy_official_text_observed": job["condition"] == "healthy_reader" and
                  any(event.get("name") == "read_pptx" and event["result"].startswith("File:") for event in env.events)}
    save(directory / "messages.json", messages)
    save(directory / "tool_events.json", env.events)
    save(final_path, result)
    return result


def run(prepared, dest, queue, base_url, concurrency):
    import fcntl  # Only the explicit run path needs a process lock.
    config = validate(prepared)
    if concurrency is None:
        concurrency = config["concurrency"]
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.path.rstrip("/") != "/v1":
        raise RuntimeError("This runner accepts only an explicit local http://127.0.0.1:PORT/v1 endpoint")
    if not 1 <= concurrency <= config["concurrency"]:
        raise RuntimeError(f"Concurrency must be 1..{config['concurrency']}")
    jobs = json.loads((prepared / ("jobs.json" if queue == "main" else "control_jobs.json")).read_text())
    cases = {case["id"]: case for case in config["cases"]}
    dest.mkdir(parents=True, exist_ok=True)
    with (dest / "worker.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        identity = {"prepared_manifest_sha256": digest(prepared / "manifest.json"),
                    "queue": queue, "base_url": base_url, "concurrency": concurrency,
                    "expected": len(jobs), "model": config["model"], "model_revision": config["model_revision"]}
        launch = dest / "launch.json"
        if launch.exists() and json.loads(launch.read_text()) != identity:
            raise RuntimeError("Result directory belongs to a different launch")
        save(launch, identity)
        # Does not load a model or start a server. Actual setup must be authorized
        # and performed separately with the configured server launcher.
        with urlopen(base_url.rstrip("/") + "/models", timeout=10) as response:
            models = json.load(response)
        if not any(model["id"] == config["served_model_name"] for model in models["data"]):
            raise RuntimeError("Expected local served model is not available")
        save(dest / "server_models.json", models)
        results = []
        started = stamp()
        progress = {"status": "running", "started_at": started, "expected": len(jobs), "finished": 0}
        save(dest / "progress.json", progress)
        try:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = {pool.submit(run_episode, job, cases[job["case_id"]], config, dest,
                                       base_url.rstrip("/")): job for job in jobs}
                for future in as_completed(futures):
                    results.append(future.result())
                    progress.update(finished=len(results), updated_at=stamp(),
                                    statuses=dict(Counter(result["status"] for result in results)))
                    save(dest / "progress.json", progress)
        except BaseException:
            progress.update(status="interrupted", updated_at=stamp())
            save(dest / "progress.json", progress)
            raise
        progress.update(status="finished", finished_at=stamp())
        save(dest / "progress.json", progress)
        save(dest / "completion.json", {**progress, "results": results})
        print(json.dumps({k: v for k, v in progress.items() if k != "results"}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "validate"):
        p = sub.add_parser(name)
        p.add_argument("--prepared", type=Path, default=DEFAULT_PREPARED)
    p = sub.add_parser("judge-packets", help="Export completed public traces locally; no judging")
    p.add_argument("--prepared", type=Path, default=DEFAULT_PREPARED)
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("run")
    p.add_argument("--execute", action="store_true", help="Explicitly enable model requests")
    p.add_argument("--prepared", type=Path, default=DEFAULT_PREPARED)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--queue", choices=("main", "controls"), default="main")
    p.add_argument("--base-url", default="http://127.0.0.1:8765/v1")
    p.add_argument("--concurrency", type=int, help="Defaults to the frozen configuration's limit")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.prepared.resolve())
    elif args.command == "validate":
        validate(args.prepared.resolve())
        print("Frozen files and job matrix validated; no model requests.")
    elif args.command == "judge-packets":
        judge_packets(args.prepared.resolve(), args.results.resolve(), args.output.resolve())
    else:
        if not args.execute:
            parser.error("run requires --execute; preparation never starts inference")
        run(args.prepared.resolve(), args.output.resolve(), args.queue, args.base_url, args.concurrency)


if __name__ == "__main__":
    main()
