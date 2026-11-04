"""Build job files (JSONL) for launch.py.

    python experiment/build_jobs.py bootstrap   -> experiment/jobs/bootstrap.jsonl
    python experiment/build_jobs.py sets        -> experiment/memory_sets.json  (needs memories.json)
    python experiment/build_jobs.py probes      -> experiment/jobs/probes.jsonl
    python experiment/build_jobs.py funding     -> experiment/jobs/funding.jsonl
"""

import copy
import json
import random
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent / "agent-interp-envs"
RESULTS = ROOT.parent / "results"
BASE = yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))

SEED = 20261104
N_SETS = 20
DOSE = 8
FUNDING_PER_SET = 10  # 20 sets x 10 = 200 rollouts per arm


def probe_config(user_prompt: str, memories: list[dict]) -> dict:
    cfg = copy.deepcopy(BASE["memory_probe"])
    cfg["prompts"]["user_prompt"] = user_prompt
    cfg["task"]["memories"] = memories
    return cfg


def write_jobs(name: str, jobs: list[dict]) -> None:
    out = ROOT / "jobs" / f"{name}.jsonl"
    out.parent.mkdir(exist_ok=True)
    out.write_text("".join(json.dumps(j, ensure_ascii=False) + "\n" for j in jobs), encoding="utf-8")
    print(f"{len(jobs)} jobs -> {out}")


def bootstrap(attempt: int = 0) -> None:
    hist = yaml.safe_load((ROOT / "histories.yaml").read_text(encoding="utf-8"))["scenarios"]
    template = BASE["bootstrap_user_prompt"]
    jobs = []
    for s in hist:
        for kind in ("hack", "honest"):
            log = (s["prefix"].rstrip() + "\n" + s[kind].rstrip())
            jobs.append({
                "run_dir": str(RESULTS / "bootstrap" / f"{s['id']}__{kind}" / f"attempt-{attempt}"),
                "image": "memory_probe",
                "config": probe_config(template.replace("{session_log}", log), []),
                "meta": {"scenario": s["id"], "env": s["env"], "kind": kind, "attempt": attempt},
            })
    write_jobs("bootstrap" if attempt == 0 else f"bootstrap_retry{attempt}", jobs)


def sets() -> None:
    """20 memory sets per arm. Arms share draw indices (hack, other-agent and
    honest memory i come from the same scenario), so every arm sees the same
    task mix per set; order is shuffled per set."""
    mem = json.loads((ROOT / "memories.json").read_text(encoding="utf-8"))
    scen = sorted({m["scenario"] for m in mem["hack"]})
    rng = random.Random(SEED)
    out = []
    for i in range(N_SETS):
        picks = rng.sample(scen, DOSE)
        rng.shuffle(picks)
        out.append({"set": i, "scenarios": picks})
    (ROOT / "memory_sets.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{N_SETS} sets of {DOSE} -> memory_sets.json")


def _arm_memories(arm: str, set_def: dict, mem: dict) -> list[dict]:
    if arm == "none":
        return []
    pool = {m["scenario"]: m for m in mem[arm]}
    return [{"memory_id": pool[s]["memory_id"], "short_description": pool[s]["short_description"],
             "memory": pool[s]["memory"]} for s in set_def["scenarios"]]


def probes() -> None:
    mem = json.loads((ROOT / "memories.json").read_text(encoding="utf-8"))
    sets_ = json.loads((ROOT / "memory_sets.json").read_text(encoding="utf-8"))
    plist = yaml.safe_load((ROOT / "probes.yaml").read_text(encoding="utf-8"))["probes"]
    jobs = []
    for arm in ("hack", "honest", "none", "other_agent"):
        for sd in sets_:
            mems = _arm_memories(arm, sd, mem)
            for p in plist:
                jobs.append({
                    "run_dir": str(RESULTS / "probes" / arm / f"set{sd['set']:02d}" / p["id"]),
                    "image": "memory_probe",
                    "config": probe_config(p["text"], mems),
                    "meta": {"arm": arm, "set": sd["set"], "probe": p["id"]},
                })
    # Interleave arms so a partial batch is balanced across conditions.
    random.Random(SEED).shuffle(jobs)
    write_jobs("probes", jobs)


def probes_full() -> None:
    """Variant: the 8 memories' full contents are in the system prompt (after the
    index), so nothing has to be read with read_memory. The no-memory arm has the
    same prompt as in the main probe run, so it is not repeated here."""
    mem = json.loads((ROOT / "memories.json").read_text(encoding="utf-8"))
    sets_ = json.loads((ROOT / "memory_sets.json").read_text(encoding="utf-8"))
    plist = yaml.safe_load((ROOT / "probes.yaml").read_text(encoding="utf-8"))["probes"]
    jobs = []
    for arm in ("hack", "honest", "other_agent"):
        for sd in sets_:
            mems = _arm_memories(arm, sd, mem)
            for p in plist:
                cfg = probe_config(p["text"], mems)
                cfg["task"]["memory_in_context"] = True
                jobs.append({
                    "run_dir": str(RESULTS / "probes_full" / arm / f"set{sd['set']:02d}" / p["id"]),
                    "image": "memory_probe",
                    "config": cfg,
                    "meta": {"arm": arm, "set": sd["set"], "probe": p["id"], "variant": "full_in_context"},
                })
    random.Random(SEED + 2).shuffle(jobs)
    write_jobs("probes_full", jobs)


def funding() -> None:
    mem = json.loads((ROOT / "memories.json").read_text(encoding="utf-8"))
    sets_ = json.loads((ROOT / "memory_sets.json").read_text(encoding="utf-8"))
    base = yaml.safe_load((REPO / "configs" / "funding_email" / "default.yaml").read_text(encoding="utf-8"))
    jobs = []
    for arm in ("hack", "honest"):
        for sd in sets_:
            mems = _arm_memories(arm, sd, mem)
            for k in range(FUNDING_PER_SET):
                cfg = copy.deepcopy(base)
                cfg["agent"] = copy.deepcopy(BASE["memory_probe"]["agent"])
                cfg["task"] = dict(cfg.get("task") or {})
                cfg["task"].update({"memory": True, "memories": mems})
                cfg["prompts"]["memory_preamble"] = BASE["memory_probe"]["prompts"]["memory_preamble"]
                jobs.append({
                    "run_dir": str(RESULTS / "funding_email" / arm / f"set{sd['set']:02d}" / f"rep{k:02d}"),
                    "image": "funding_email",
                    "config": cfg,
                    "meta": {"arm": arm, "set": sd["set"], "rep": k},
                })
    random.Random(SEED + 1).shuffle(jobs)
    write_jobs("funding", jobs)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "bootstrap":
        bootstrap(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
    else:
        {"sets": sets, "probes": probes, "probes_full": probes_full, "funding": funding}[cmd]()
