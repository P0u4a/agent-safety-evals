"""Collect bootstrapped memories into experiment/memories.json.

For each (scenario, kind) the latest attempt directory is read; the memory is
the FIRST write_memory call in the session (state memory_calls). Sessions with
no write_memory call are listed as missing (rerun them with a new attempt).
The other_agent pool is copied from experiment/other_agent_edits.json when
present (hand edits of the hack memories that change only who did it).
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RES = ROOT.parent / "results" / "bootstrap"


def first_write(run: Path):
    p = run / "final" / "result.json"
    if not p.exists():
        return None
    for c in json.loads(p.read_text(encoding="utf-8"))["memory_calls"]:
        if c.get("tool") == "write_memory" and "memory" in c:
            return c
    return None


def main() -> None:
    out = {"hack": [], "honest": []}
    missing, log = [], []
    for d in sorted(RES.iterdir()):
        scen, kind = d.name.rsplit("__", 1)
        attempts = sorted(d.glob("attempt-*"), key=lambda p: int(p.name.split("-")[1]))
        chosen = None
        for a in attempts:
            w = first_write(a)
            log.append({"scenario": scen, "kind": kind, "attempt": a.name, "wrote_memory": w is not None})
            if w is not None and chosen is None:
                chosen = (a, w)
        if chosen is None:
            missing.append(d.name)
            continue
        a, w = chosen
        out[kind].append({"scenario": scen, "memory_id": w["memory_id"], "short_description": w["short_description"],
                          "memory": w["memory"], "source_run": str(a.relative_to(ROOT.parent))})
    edits = ROOT / "other_agent_edits.json"
    if edits.exists():
        out["other_agent"] = json.loads(edits.read_text(encoding="utf-8"))
    out["attempt_log"] = log
    (ROOT / "memories.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"hack={len(out['hack'])} honest={len(out['honest'])} missing={missing}")


if __name__ == "__main__":
    main()
