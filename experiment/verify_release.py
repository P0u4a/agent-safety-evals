"""Check frozen release inputs, report copies and Python syntax without inference."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    checked = 0
    for manifest in ('experiment/inputs/manifest.json', 'results/manifest.json'):
        entries = json.loads((ROOT / manifest).read_text())
        for name, record in entries.items():
            path = (ROOT / name).resolve()
            if not path.is_relative_to(ROOT):
                raise ValueError(f'Path outside release: {name}')
            if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
                raise ValueError(f'Frozen release artifact changed: {name}')
            checked += 1
    scripts = [p for p in (ROOT / 'experiment').rglob('*.py')
               if not {'prepared', 'jobs', '__pycache__'}.intersection(p.parts)]
    for path in scripts:
        ast.parse(path.read_text(), filename=str(path))
    print(f'Validated {checked} frozen artifacts and {len(scripts)} Python files; no inference.')


if __name__ == '__main__':
    main()
