"""Verify phase boundaries, actual effects and retained tool histories in native controls."""
import json,sys,hashlib
from pathlib import Path
from collections import Counter
import yaml
from prepare_funding_judging import effective_email
from run_lfm_funding_checkpoint_v2 import DEFAULT_OUTPUT,CONTINUATION,digest,ROOT,stamp

def audit(dest):
 result=[]
 for job in json.loads((dest/'control_jobs.json').read_text()):
  d=dest/'controls/runs'/job['id'];r=json.loads((d/'result.json').read_text())
  cfg=yaml.safe_load((d/'config.yaml').read_text());review=json.loads((d/'review/result.json').read_text());prefix=json.loads((d/'review/continuation_messages.json').read_text());request=json.loads((d/'review/request.json').read_text())
  expected=[{'role':'system','content':cfg['prompts']['system_prompt']},{'role':'user','content':cfg['prompts']['user_prompt']}]
  assert request['messages']==prefix[:2]==expected
  assert not any(k in request['kwargs'] for k in ['tools','parallel_tool_calls','tool_choice'])
  assert len(prefix)==4 and prefix[2]['content']==review['answer'] and prefix[-1]=={'role':'user','content':CONTINUATION}
  steps=sorted(d.glob('step-*/messages.json'),key=lambda f:int(f.parent.name[5:]));messages=json.loads(steps[-1].read_text());state=json.loads((steps[-1].parent/'state.json').read_text())
  assert messages[:4]==prefix
  for f in steps:
   earlier=json.loads(f.read_text());assert earlier==messages[:len(earlier)]
  assert all(m['role']!='user' for m in messages[4:]),'Unexpected harness/user nudge'
  assert r['discarded_turns']==0 and r['technical_control_passed'] and r['rc']==0 and not r['truncated']
  trace=[json.loads(l) for l in (d/'requests.jsonl').read_text().splitlines()]
  requests=[t for t in trace if t['event']=='request'];responses=[t for t in trace if t['event']=='response'];assert len(requests)==len(responses)
  actual=[m for m in messages if m['role']=='assistant'][1 if job.get('replay') else 0:]
  assert [t['message'] for t in responses]==actual
  for t in requests:
   kw=t['kwargs'];assert kw['temperature']==0.6 and kw['top_p']==0.95 and kw['max_tokens']==65536
  action_requests=[t for t in requests if t['kwargs'].get('tools')];assert action_requests
  assert action_requests[0]['messages'][-1]=={'role':'user','content':CONTINUATION}
  assert len(requests)-len(action_requests)==(0 if job.get('replay') else 1)
  calls={};returns={};last_update=None
  for m in messages[4:]:
   if m['role']=='assistant':
    for t in m.get('tool_calls')or[]:
     assert t['id'] not in calls;calls[t['id']]=t['function']
   if m['role']=='tool':
    assert m['tool_call_id'] in calls and m['tool_call_id'] not in returns;returns[m['tool_call_id']]=m['content']
    c=calls[m['tool_call_id']]
    if c['name']=='update_email' and m['content']=='Email draft updated successfully.':
     args=json.loads(c['arguments']);assert set(args)=={'subject','body'} and all(isinstance(v,str) for v in args.values());last_update=args
  assert set(calls)==set(returns)
  email,source=effective_email(d)
  assert state['email_updated']==bool(last_update)
  if last_update:assert state['submitted_report']==email and '\nSubject: '+last_update['subject']+'\n\n'+last_update['body']+'\n' in email
  assert state['termination_reason']==r['termination_reason'] and r['rollout_terminated']
  result.append(dict(id=job['id'],kind=job['control_type'],review_answer_chars=len(review['answer']),status=r['status'],termination_reason=r['termination_reason'],tools=dict(Counter(c['name'] for c in calls.values())),email_updated=state['email_updated'],public_action_messages=[m['content'] for m in messages[4:] if m['role']=='assistant' and m.get('content')],requests=len(requests),no_user_nudges=True,no_discarded_turns=True,request_response_history_verified=True,effective_email_verified=True))
 save={'at':stamp(),'automated_checks_passed':True,'records':result,'script_sha256':digest(Path(__file__)),'note':'Technical validation only. No gate on moral choice or factual correctness; separate primary review still required.'}
 (dest/'native_control_audit.json').write_text(json.dumps(save,indent=2)+'\n');print(json.dumps(save,indent=2))
if __name__=='__main__':audit(DEFAULT_OUTPUT)
