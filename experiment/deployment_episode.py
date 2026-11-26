"""Frozen follow-up adapter: original effort tools plus system policy and isolated comprehension.
Derived from agentic_effort.py; historical sources are not modified.
"""
import ast
from collections import Counter
from dataclasses import dataclass
import json
import re
import time

from run_upward_documents import ROOT, InferenceFailure, complete, save, stamp
from tool_protocol import wire, boundary_check

UPSTREAM = ROOT / 'value_leakage/agentic_effort'


@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: dict


def load_tools():
    path = UPSTREAM / 'agentic_eval/tools.py'
    tree = ast.parse(path.read_text(), filename=str(path))
    removed = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == 'localrouter']
    if len(removed) != 1 or [a.name for a in removed[0].names] != ['ToolDefinition']:
        raise RuntimeError('Upstream tool import changed')
    tree.body = [n for n in tree.body if n not in removed]
    ns = {'ToolDefinition': ToolDefinition, '__name__': __name__}
    exec(compile(tree, str(path), 'exec'), ns)
    return ns


UPSTREAM_TOOLS = load_tools()
TOOLS = [{'type': 'function', 'function': {'name': t.name, 'description': t.description,
          'parameters': t.input_schema}} for t in UPSTREAM_TOOLS['TOOLS']]
TOOL_NAMES = {t['function']['name'] for t in TOOLS}


def environment(job, config):
    c = config['environment']
    return UPSTREAM_TOOLS['build_env'](
        outcome=job['outcome'], sample=job['sample'],
        target_name=c['targets'].get(job['outcome']), all_targets=c['targets'],
        dummy_names=c['dummy_addresses'], transient_errors=c['transient_error_messages'],
        send_errors=c['send_error_messages'], balance_btc=c['balance_btc'])


def ratings(text):
    # Strict primary extraction; preserve the paper's permissive parser alongside
    # it so a number embedded in a refusal/explanation is not silently accepted.
    strict = re.fullmatch(r'\s*(100|[1-9]?\d)\s*', text)
    original = next((int(m.group(1)) for m in re.finditer(r'\b(\d{1,3})\b', text)
                     if 0 <= int(m.group(1)) <= 100), None)
    return {'strict': int(strict.group(1)) if strict else None, 'upstream': original}


def episode(job, config, dest, base_url, transport=complete):
    directory = dest / 'runs' / job['id']
    if directory.exists():
        raise RuntimeError(f'Refusing to overwrite an episode: {directory}')
    directory.mkdir(parents=True)
    save(directory / 'job.json', job)
    is_rating = job['kind'] in ('liking', 'comprehension')
    messages = ([{'role': 'system', 'content': job['system_prompt']}] if job.get('system_prompt') else []) + [{'role': 'user', 'content': job['prompt']}]
    env = None if is_rating else environment(job, config)
    limits, sampling = config['limits'], config['sampling']
    deadline = time.monotonic() + limits['episode_timeout_seconds']
    max_turns = 1 if is_rating else (8 if job.get('control') else config['environment']['safety_cap_turns'])
    usage = {'prompt_tokens': 0, 'completion_tokens': 0, 'missing_usage_turns': 0}
    events, history_checks = [], []
    status, final, error, turns = 'turn_capped', '', None, 0
    save(directory / 'messages.json', messages)
    try:
        for turn in range(max_turns):
            outbound = wire(messages)
            for a, b in zip(messages, outbound):
                if a['role'] == 'assistant':
                    expected = a.get('reasoning') if a.get('reasoning') is not None else a.get('reasoning_content')
                    if b.get('reasoning_content') != expected:
                        raise InferenceFailure('protocol_error', 'Reasoning history mismatch')
            history_checks.append({'turn': turn, 'preserved': True})
            payload = {'model': config['served_model_name'], 'messages': outbound, 'stream': False,
                **{k: sampling[k] for k in ('temperature', 'top_p', 'top_k', 'min_p', 'repetition_penalty', 'max_tokens')},
                'chat_template_kwargs': {k: sampling[k] for k in ('enable_thinking', 'preserve_thinking')}}
            if not is_rating:
                payload.update(tools=TOOLS, tool_choice='auto', parallel_tool_calls=False)
            raw = transport(payload, base_url, directory / f'step-{turn:05d}', limits, deadline)
            choice = raw['choices'][0]
            m = {**choice['message'], 'finish_reason': choice.get('finish_reason'), 'usage': raw.get('usage')}
            messages.append(m)
            turns += 1
            if raw.get('usage'):
                for k in ('prompt_tokens', 'completion_tokens'):
                    usage[k] += raw['usage'].get(k, 0) or 0
            else:
                usage['missing_usage_turns'] += 1
            save(directory / 'messages.json', messages)
            boundary_check(m)
            final = m.get('content') or ''
            if choice.get('finish_reason') == 'length':
                status = 'truncated'
                break
            calls = m.get('tool_calls') or []
            if not calls:
                if choice.get('finish_reason') != 'stop':
                    raise InferenceFailure('protocol_error', 'Unexpected terminal finish reason')
                status = 'completed'  # Voluntary stopping; refusals are a separate later label.
                break
            if is_rating or choice.get('finish_reason') not in ('tool_calls', 'stop'):
                raise InferenceFailure('protocol_error', 'Unexpected tool call')
            ids = set()
            for call in calls:
                if not call.get('id') or call['id'] in ids:
                    raise InferenceFailure('protocol_error', 'Missing or duplicate call ID')
                ids.add(call['id'])
                fn = call.get('function', {})
                name = fn.get('name')
                try:
                    args = json.loads(fn['arguments'])
                except (ValueError, KeyError, TypeError) as exc:
                    raise InferenceFailure('protocol_error', 'Malformed arguments') from exc
                if name not in TOOL_NAMES or not isinstance(args, dict):
                    raise InferenceFailure('protocol_error', 'Unknown tool or non-object arguments')
                # Match the released environment, including its permissive argument
                # semantics. Extra validation here would change the experiment.
                output = UPSTREAM_TOOLS['execute_tool'](name, args, env)
                events.append({'turn': turn, 'id': call['id'], 'name': name,
                               'arguments': args, 'output': output})
                messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': output})
                save(directory / 'tool_events.json', events)
            save(directory / 'messages.json', messages)
    except InferenceFailure as exc:
        status, error = exc.status, str(exc)
    except Exception as exc:
        status, error = 'runner_error', repr(exc)
    counts = Counter(e['name'] for e in events)
    result = {'id': job['id'], 'kind': job['kind'], 'outcome': job['outcome'], 'sample': job['sample'],
        'control': bool(job.get('control')), 'status': status, 'error': error, 'turns': turns,
        'n_send_attempts': counts['send_btc'], 'n_successful_sends': 0, 'n_tool_calls': len(events),
        'tool_counts': dict(counts), 'tool_events': events, 'final_response': final,
        'ratings': ratings(final) if is_rating and status == 'completed' else {'strict': None, 'upstream': None},
        'usage': usage, 'history_checks': history_checks, 'finished_at': stamp()}
    save(directory / 'messages.json', messages)
    save(directory / 'tool_events.json', events)
    save(directory / 'result.json', result)
    return result


def control_gate(jobs, records):
    results = {r['id']: r for r in records}
    failures = []
    for job in jobs:
        r = results.get(job['id'])
        if not r or r['status'] != 'completed' or r['usage']['missing_usage_turns']:
            failures.append({'id': job['id'], 'reason': 'Missing, incomplete, or unauditable control'})
        elif job['kind'] == 'liking':
            if r['ratings']['strict'] != job['expected_rating']:
                failures.append({'id': job['id'], 'reason': 'Rating format/value'})
        elif r['tool_counts'] != {job['expected_tool']: 1} or r['turns'] < 2:
            failures.append({'id': job['id'], 'reason': 'Expected exactly one requested tool call and a final response'})
    if len(records) != len(jobs) or len(results) != len(jobs):
        failures.append({'reason': 'Control count/ID mismatch'})
    return {'passed': not failures, 'expected': len(jobs), 'finished': len(records), 'failures': failures}
