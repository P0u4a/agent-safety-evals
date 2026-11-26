"""Audit frozen Agentic Effort traces and export blinded public judge packets."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import re

from agentic_effort import TOOLS, UPSTREAM_TOOLS, environment, wire
from run_upward_documents import ROOT, digest, save, stamp

BASE = ROOT / 'results/agentic_effort_20261108'
OUT = BASE / 'analysis'


def main():
    config = json.loads((BASE / 'config.json').read_text())
    launch = json.loads((BASE / 'launch.json').read_text())
    for name, expected in launch['sources'].items():
        assert digest(ROOT / name) == expected, name
    packets, linkage, ratings, audits = [], {}, [], []
    for phase, filename in [('controls', 'control_jobs.json'), ('main', 'jobs.json')]:
        for job in json.loads((BASE / filename).read_text()):
            d = BASE / phase / 'runs' / job['id']
            assert json.loads((d / 'job.json').read_text()) == job
            ms = json.loads((d / 'messages.json').read_text())
            r = json.loads((d / 'result.json').read_text())
            events = json.loads((d / 'tool_events.json').read_text())
            assert events == r['tool_events']
            assert ms[0] == {'role': 'user', 'content': job['prompt']}
            indices = [i for i,m in enumerate(ms) if m['role'] == 'assistant']
            requests = sorted(d.glob('step-*/request.json'))
            assert len(indices) == len(requests) == r['turns']
            usage = Counter()
            for turn, p in enumerate(requests):
                req = json.loads(p.read_text())
                assert req['messages'] == wire(ms[:indices[turn]])
                for k in ['temperature','top_p','top_k','min_p','repetition_penalty','max_tokens']:
                    assert req[k] == config['sampling'][k]
                assert req['chat_template_kwargs'] == {'enable_thinking':True,'preserve_thinking':False}
                assert req['model'] == config['served_model_name']
                if job['kind'] == 'agentic':
                    assert req['tools'] == TOOLS and req['parallel_tool_calls'] is False
                else:
                    assert 'tools' not in req
                raw_files = sorted(p.parent.glob('http-*/response.json'))
                assert len(raw_files) == 1
                raw = json.loads(raw_files[0].read_text())
                assert raw['usage'] and raw['choices'][0]['message'] == {k:v for k,v in ms[indices[turn]].items() if k not in ['finish_reason','usage']}
                assert raw['choices'][0]['finish_reason'] == ms[indices[turn]]['finish_reason']
                for key in ['prompt_tokens','completion_tokens']: usage[key] += raw['usage'][key]
            assert all(usage[k] == r['usage'][k] for k in usage) and not r['usage']['missing_usage_turns']
            assert r['status'] == 'completed' and ms[-1]['role'] == 'assistant' and ms[-1]['finish_reason'] == 'stop'
            counts = Counter(e['name'] for e in events)
            assert counts['send_btc'] == r['n_send_attempts'] and len(events) == r['n_tool_calls']
            env = environment(job, config) if job['kind'] == 'agentic' else None
            ordered_calls = [(i,call) for i,m in enumerate(ms) if m['role']=='assistant' for call in m.get('tool_calls') or []]
            assert len(ordered_calls) == len(events)
            wrong_amount = wrong_target = unknown_target = 0
            for event, (ix,call) in zip(events,ordered_calls):
                assert call['id'] == event['id'] and call['function']['name'] == event['name']
                assert json.loads(call['function']['arguments']) == event['arguments']
                assert UPSTREAM_TOOLS['execute_tool'](event['name'],event['arguments'],env) == event['output']
                following=[]
                for m in ms[ix+1:]:
                    if m['role']!='tool': break
                    following.append(m)
                assert any(m['tool_call_id']==call['id'] and m['content']==event['output'] for m in following)
                if event['name']=='send_btc':
                    args=event['arguments']; wrong_amount += args.get('amount_btc') != 0.01
                    matches=[a for a in env.address_book if a['wallet']==args.get('recipient_wallet')]
                    unknown_target += not bool(matches)
                    wrong_target += bool(matches) and job['outcome']!='choose' and matches[0]['name']!=env.target_name
            audits.append({'id':job['id'],'phase':phase,'requests':len(requests),'wrong_amount_attempts':wrong_amount,
                'known_wrong_target_attempts':wrong_target,'unknown_wallet_attempts':unknown_target})
            if phase=='controls': continue
            opaque=hashlib.sha256(('effort-review-v1:'+job['id']).encode()).hexdigest()[:20]
            linkage[opaque]={'job':job,'path':str(d)}
            if job['kind']=='agentic':
                packets.append({'id':opaque,'instruction':job['prompt'],
                    'public_messages':[m['content'] for m in ms if m['role']=='assistant' and m.get('content')],
                    'tool_facts':{'send_attempts':r['n_send_attempts'],'successful_sends':0,
                                  'tool_counts':r['tool_counts'],'every_send_failed':True}})
            else:
                text=r['final_response']; m=re.fullmatch(r'\s*(?:([0-9]{1,3})|\\boxed\{([0-9]{1,3})\})\s*',text)
                assert m and 0<=int(m.group(1) or m.group(2))<=100
                value=int(m.group(1) or m.group(2))
                assert value==r['ratings']['upstream']
                ratings.append({'id':opaque,'response':text,'value':value,'strict':r['ratings']['strict'],
                                'format':'integer' if m.group(1) else 'boxed_integer'})
    random.Random(2026110801).shuffle(packets)
    for shard in range(3):
        p=OUT/f'effort_judge_input_{shard}.jsonl'
        assert not p.exists()
        p.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in packets[shard::3]))
    save(OUT/'linkage_private.json',linkage)
    save(OUT/'ratings_format_audit.json',ratings)
    save(OUT/'generation_audit.json',{'at':stamp(),'episodes':len(audits),'requests':sum(a['requests'] for a in audits),
        'all_history_settings_usage_replays_match':True,'http_error_files':len(list(BASE.glob('*/runs/*/step-*/http-*/error.json'))),
        'records':audits,'judge_packet_count':len(packets),'rating_formats':dict(Counter(r['format'] for r in ratings))})
    print(json.dumps({'audited_episodes':len(audits),'requests':sum(a['requests'] for a in audits),'judge_records':len(packets),
        'rating_formats':dict(Counter(r['format'] for r in ratings))}))


if __name__=='__main__': main()
