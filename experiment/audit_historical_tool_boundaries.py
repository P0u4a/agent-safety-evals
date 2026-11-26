"""Check retained and discarded historical responses for unparsed tool markup.

Read-only over generation artifacts. No model requests or tool-call execution.
Latest cumulative message/discard logs are used to avoid counting checkpoints
of the same assistant response repeatedly. Report candidate patterns separately
from the precise empty-stop signature observed in Secret Number.
"""
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/historical_tool_boundary_audit'


def read(path):
    return json.loads(path.read_text())


def step_index(path):
    return int(path.parent.name.split('-')[1])


def inspect_run(path, group, archive=False):
    files = sorted(path.glob('step-*/messages.json'), key=step_index)
    result = {'run': str(path.relative_to(ROOT)), 'group': group, 'archived_attempt': archive,
              'checkpoint_files': len(files), 'latest_messages': str(files[-1].relative_to(ROOT)) if files else None}
    if not files:
        result['missing_messages'] = True
        error_path = path / 'error.json'
        if error_path.exists():
            error = read(error_path)
            result['error_step'] = error.get('step')
            result['error_types'] = [e.get('type') for e in error.get('chain', [])]
        log_path = path / 'rollout.log'
        if log_path.exists():
            log = log_path.read_text()
            result['log_response_sections'] = log.count('RESPONSE')
            result['log_reasoning_sections'] = log.count('REASONING')
            result['log_tool_markup_present'] = '<tool_call>' in log or '<function=' in log
        return result, []
    result['latest_messages_sha256'] = hashlib.sha256(files[-1].read_bytes()).hexdigest()
    messages = read(files[-1])
    kept = [(i, m) for i, m in enumerate(messages) if m.get('role') == 'assistant']
    disc_paths = sorted(path.glob('step-*/discarded.json'), key=step_index)
    discarded = max((read(p) for p in disc_paths), key=len, default=[])
    counts = Counter()
    flags = []
    generated = [('retained', i, m) for i, m in kept]
    generated += [('discarded', i, d['message']) for i, d in enumerate(discarded)]
    for origin, index, m in generated:
        reason = m.get('reasoning_content') or m.get('reasoning') or ''
        content = m.get('content') or ''
        calls = m.get('tool_calls') or []
        counts[origin + '_responses'] += 1
        counts[origin + '_with_reasoning'] += bool(reason)
        counts[origin + '_with_api_tools'] += bool(calls)
        counts[origin + '_empty_stop'] += (not content and not calls and m.get('finish_reason') == 'stop')
        r_markup = '<tool_call>' in reason or '<function=' in reason
        c_markup = '<tool_call>' in content or '<function=' in content
        if not r_markup and not (c_markup and not calls):
            continue
        blocks = re.findall(r'<tool_call>\s*(.*?)\s*</tool_call>', reason, re.S)
        names = [name for block in blocks for name in re.findall(r'<function=([^>]+)>', block)]
        exact = bool(blocks and reason.rstrip().endswith('</tool_call>') and not content
                     and not calls and m.get('finish_reason') == 'stop')
        counts[origin + '_reasoning_markup'] += r_markup
        counts[origin + '_public_markup_without_api_tools'] += c_markup and not calls
        counts[origin + '_exact_empty_stop_signature'] += exact
        flags.append({'run': result['run'], 'group': group, 'archived_attempt': archive,
                      'origin': origin, 'message_index': index,
                      'is_last_retained_assistant': origin == 'retained' and index == kept[-1][0],
                      'finish_reason': m.get('finish_reason'), 'public_content_length': len(content),
                      'api_tool_names': [t.get('function', {}).get('name') for t in calls],
                      'reasoning_tool_block_names': names,
                      'reasoning_ends_with_tool_block': reason.rstrip().endswith('</tool_call>'),
                      'reasoning_tool_markup': r_markup, 'public_tool_markup': c_markup,
                      'exact_empty_stop_signature': exact,
                      'completion_tokens': (m.get('usage') or {}).get('completion_tokens')})
    result.update(counts)
    result['discarded_response_count'] = len(discarded)
    result['last_assistant_finish_reason'] = kept[-1][1].get('finish_reason') if kept else None
    result['last_assistant_public_content_length'] = len(kept[-1][1].get('content') or '') if kept else 0
    result['last_assistant_api_tools'] = [c['function']['name'] for c in (kept[-1][1].get('tool_calls') or [])] if kept else []
    return result, flags


def main():
    jobs = []
    general = ROOT / 'results/general_agent_4bit_20261106'
    for env in ['funding_email', 'currency_conversion']:
        jobs += [(p.parent, 'memory_free/' + env, False) for p in sorted((general / env).glob('rep*/attempt-*/launch.json'))]
    records, flags = [], []
    for path, group, archive in jobs:
        record, found = inspect_run(path, group, archive)
        records.append(record)
        flags.extend(found)
    grouped = defaultdict(list)
    for r in records:
        grouped[r['group']].append(r)
    summary = {}
    count_keys = ['retained_responses', 'discarded_responses', 'retained_with_reasoning', 'discarded_with_reasoning',
                  'retained_with_api_tools', 'discarded_with_api_tools', 'retained_empty_stop', 'discarded_empty_stop',
                  'retained_reasoning_markup', 'discarded_reasoning_markup', 'retained_exact_empty_stop_signature',
                  'discarded_exact_empty_stop_signature', 'retained_public_markup_without_api_tools',
                  'discarded_public_markup_without_api_tools']
    for group, rows in grouped.items():
        summary[group] = {'runs': len(rows), 'missing_messages': sum(r.get('missing_messages', False) for r in rows),
                          **{k: sum(r.get(k, 0) for r in rows) for k in count_keys},
                          'runs_with_exact_signature': sum(bool(r.get('retained_exact_empty_stop_signature', 0)
                                                               or r.get('discarded_exact_empty_stop_signature', 0)) for r in rows)}
    OUT.mkdir(exist_ok=True)
    for name, rows in [('runs.jsonl', records), ('flagged_responses.jsonl', flags)]:
        (OUT / name).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    doc = {'created_at': datetime.now(timezone.utc).isoformat(), 'groups': summary,
           'canonical_runs': sum(r['runs'] for r in summary.values()),
           'canonical_responses_including_discarded': sum(r['retained_responses'] + r['discarded_responses']
               for r in summary.values()),
           'archive_missing_transcripts': [r for r in records if r.get('missing_messages')],
           'scope': 'Historical memory-free Funding Email and Broken Calculator attempts. Scripted preflight excluded.',
           'method': 'Inspect all assistant responses in latest cumulative messages and longest discarded log. Exact signature requires terminal tool block in reasoning, empty public content, no API tool calls and finish_reason stop. Other markup patterns are candidates needing review, not automatically failures.',
           'model_requests': 0, 'generation_artifacts_modified': False}
    (OUT / 'summary.json').write_text(json.dumps(doc, indent=2) + '\n')
    print(json.dumps(doc, indent=2))


if __name__ == '__main__':
    main()
