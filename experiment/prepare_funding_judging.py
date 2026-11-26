"""Recover the final investor draft from recorded filesystem snapshots."""
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FS = ROOT / "agent-interp-envs/environments/funding_email/filesystem"


def effective_email(run):
    snapshots = sorted(run.glob("step-*/fs/manifest.json"), key=lambda p:int(p.parent.parent.name.split("-")[1]))
    if not snapshots:
        raise ValueError(f"No filesystem snapshot: {run}")
    manifest = json.loads(snapshots[-1].read_text())
    email_path = "/home/user/scheduled_emails/investor_email_draft.txt"
    entry = next((e for e in manifest["entries"] if e["path"] == email_path), None)
    if entry is None:
        return (FS / "scheduled_emails/investor_email_draft.txt").read_text(), "pristine"
    if entry["action"] != "write":
        return None, entry["action"]
    blob = entry["blob"]
    if len(blob) != 16 or any(c not in "0123456789abcdef" for c in blob):
        raise ValueError("Invalid blob hash")
    return gzip.decompress((run / "blobs" / f"{blob}.gz").read_bytes()).decode(), "snapshot"
