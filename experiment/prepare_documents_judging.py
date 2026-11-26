"""Export blinded Study Assistant and Grade Lookup traces; no model calls."""
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'results/selected_evals_20261107_interactive'
OUT = BASE / 'analysis'


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value, jsonl=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in value)
               if jsonl else json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    if path.exists() and path.read_text() != content:
        raise ValueError(f'Refusing to replace frozen output: {path}')
    path.write_text(content)


def main():
    launch = read(BASE / 'launch.json')
    for rel, sha in launch['sources'].items():
        assert digest(ROOT / rel) == sha, rel
    # Full bundle provenance validation; no inference is started.
    import run_upward_documents as docs
    docs.validate(ROOT / 'experiment/prepared/upward_documents_20261107_interactive')
    packets = {'documents': []}
    linkage, audit = [], []
    for phase in ['main', 'controls']:
        completion = read(BASE / phase / 'completion.json')
        assert len(completion['results']) == completion['expected'] == completion['finished']
        assert len({r['id'] for r in completion['results']}) == len(completion['results'])
        for r in completion['results']:
            if r['environment'] not in {'study_assistant', 'grade_lookup'}:
                continue
            kind = 'documents'
            path = BASE / phase / kind / 'runs' / r['id']
            assert read(path / 'result.json') == r
            assert read(path / 'tool_events.json') == r['tool_events']
            messages = read(path / 'messages.json')
            public = [m['content'] for m in messages
                      if m.get('role') == 'assistant' and m.get('content')]
            opaque = hashlib.sha256(('selected-luna-v1:' + phase + ':' + r['id']).encode()).hexdigest()[:20]
            link = {'id': opaque, 'phase': phase, 'kind': kind, 'job_id': r['id'],
                    'environment': r['environment'], 'case_id': r.get('case_id'),
                    'run_path': str(path.relative_to(BASE)), 'status': r['status']}
            linkage.append(link)
            requests = sorted(path.glob('step-*/request.json'))
            responses = sorted(path.glob('step-*/http-*/response.json'))
            errors = sorted(path.glob('step-*/http-*/error.json'))
            finishes = Counter()
            for request in requests:
                q = read(request)
                for key in ['temperature', 'top_p', 'top_k', 'min_p', 'repetition_penalty', 'max_tokens']:
                    assert q[key] == launch['sampling'][key], (request, key)
                assert q['chat_template_kwargs'] == {'enable_thinking': True, 'preserve_thinking': False}
                assert {t['function']['name'] for t in q['tools']} == {'list_dir', 'read_pptx', 'read_txt'}
            for response in responses:
                data = read(response)
                finishes.update(c['finish_reason'] for c in data['choices'])
            assert len(responses) == r['turns'], (path, len(responses), r['turns'])
            audit.append({**link, 'usage': r['usage'], 'turns': r['turns'],
                          'requests': len(requests), 'responses': len(responses),
                          'http_error_records': len(errors), 'finish_reasons': dict(finishes),
                          'outcome': r.get('outcome'), 'error': r.get('error'),
                          'reader_failure_observed': r.get('reader_failure_observed'),
                          'alternative_text_observed': r.get('alternative_text_observed'),
                          'healthy_official_text_observed': r.get('healthy_official_text_observed')})
            if r['status'] != 'completed':
                continue
            packet = {'id': opaque,
                      'instruction': next(m['content'] for m in messages if m['role'] == 'user'),
                      'public_messages': public, 'tool_events': r['tool_events']}
            packet['final_response'] = r['final_response']
            packets[kind].append(packet)
    rng = random.Random(20261107073)
    for kind, rows in packets.items():
        rng.shuffle(rows)
        save(OUT / 'inputs' / f'{kind}.jsonl', rows, True)
        # Reserve before any judge ratings, mixing real controls and main runs.
        holdout = rng.sample(rows, 12)
        save(OUT / 'calibration' / f'{kind}_holdout_input.jsonl', holdout, True)
        name = 'upward_documents'
        source = read(ROOT / 'experiment' / f'{name}_calibration.json')
        save(OUT / 'calibration' / f'{kind}_anchors_input.jsonl',
             [{k: v for k, v in a.items() if k != 'expected'} for a in source['anchors']], True)
        save(OUT / 'calibration' / f'{kind}_anchors_reference.jsonl',
             [{'id': a['id'], **a['expected']} for a in source['anchors']], True)
    save(OUT / 'linkage_private.json', linkage)
    save(OUT / 'audit.json', audit)
    save(OUT / 'manifest.json', {
        'source_completion_sha256': digest(BASE / 'completion.json'),
        'judge_inputs': {k: {'count': len(v), 'sha256': digest(OUT / 'inputs' / f'{k}.jsonl')}
                         for k, v in packets.items()},
        'assigned_audited': len(audit),
        'excluded_from_method_judging': [x for x in linkage if x['status'] != 'completed'],
        'blinding': 'Shuffled opaque IDs; no model identity, private reasoning, hidden targets/seeds, linkage, or prior ratings provided to judges.',
        'validation': 'Synthetic anchors, then 12 held-out real records per rubric against independent primary-agent references before bulk judging. Not human or probability calibration.'})
    print(json.dumps({'audited': len(audit), 'judge_records': {k: len(v) for k, v in packets.items()},
                      'http_error_records': sum(x['http_error_records'] for x in audit)}))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=BASE)
    args = parser.parse_args()
    BASE = args.results.resolve()
    OUT = BASE / 'analysis'
    main()
