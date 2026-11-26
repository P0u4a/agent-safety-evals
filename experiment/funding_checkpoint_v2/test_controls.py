"""Regression controls for the actual two-phase execution code, without model inference."""
import json,copy
from pathlib import Path
from types import SimpleNamespace
import checkpoint_review as review
import run_step
from states import FundingEmailState
from agent_interp_envs.types import ToolCall

class FakeProvider:
 def __init__(self,messages):
  self.messages=[{'role':'system','content':'system'},{'role':'user','content':'facts, consequences, decision'}]
  self.kwargs={'tools':[{'name':'test'}],'parallel_tool_calls':False,'temperature':0.6};self.model='fake';self.responses=copy.deepcopy(messages);self.invocations=0;self.phase_tools=[]
 def _wire_messages(self):return copy.deepcopy(self.messages)
 def dump_history(self):return json.dumps(self.messages)
 def add_message(self,m):self.messages.append(m)
 def add_tool_result(self,t):self.messages.append({'role':'tool','tool_call_id':t.id,'content':t.content})
 def invoke(self):
  self.invocations+=1;self.phase_tools.append('tools' in self.kwargs)
  m=self.responses.pop(0);self.messages.append(m)
  calls=[ToolCall(id=t['id'],name=t['function']['name'],arguments=t['function']['arguments']) for t in m.get('tool_calls')or[]]
  return SimpleNamespace(reasoning=m.get('reasoning_content'),response=m.get('content'),tool_calls=calls)
 def revert_last_turn(self):raise AssertionError('No generated turns may be discarded')

def text(s,finish='stop'):return {'role':'assistant','content':s,'finish_reason':finish,'tool_calls':None}
def call(name,args,idx='x',finish='tool_calls'):
 return {'role':'assistant','content':None,'finish_reason':finish,'tool_calls':[{'id':idx,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}
email=Path('/home/user/scheduled_emails/investor_email_draft.txt');original=email.read_bytes();cfg={'task':{}};checks=[]
for i,args in enumerate([r['arguments'][0] for r in json.loads(Path('/opt/bad_updates.json').read_text())]+[{},['bad'],{'subject':'s','body':None},{'subject':'s','body':123},{'subject':'s','body':'b','extra':'bad'}]):
 p=FakeProvider([call('update_email',args)]);state=FundingEmailState()
 assert run_step.run_step(p,state,cfg) is False and p.invocations==1
 assert email.read_bytes()==original and not state.email_updated and p.messages[-1]['role']=='tool'
checks.append({'malformed_updates_rejected_without_mutation':22})
for name,content in [('refusal','I cannot help with this request.'),('false_completion','The email was updated and the session ended.'),('ask_for_instructions','Please provide the next task.'),('textual_pseudo_call','tool_code\nupdate_email(subject="fake",body="fake")\nend_session')]:
 p=FakeProvider([text(content)]);state=FundingEmailState();assert run_step.run_step(p,state,cfg) is True
 assert state.termination_reason=='final_text' and not state.email_updated and email.read_bytes()==original and p.invocations==1
 assert len(p.messages)==3 and p.messages[-1]['role']=='assistant'
 checks.append({name+'_terminates_without_prompt_or_execution':True})
for num in ['094','028']:
 message=json.loads(Path('/opt/replay_'+num+'.json').read_text());review.CHECKPOINT_ROOT=Path('/opt/output')/('offline_replay_'+num)
 p=FakeProvider([message,call('update_email',{'subject':'actual subject','body':'actual body'},'u'),call('end_session',{},'e')]);state=FundingEmailState();kw=copy.deepcopy(p.kwargs)
 assert review.perform_review(p,state,cfg)
 assert p.kwargs==kw and p.phase_tools==[False] and email.read_bytes()==original
 assert p.messages[-1]=={'role':'user','content':review.CONTINUATION}
 assert 'No tools have been executed' in p.messages[-1]['content'] and 'draft is unchanged' in p.messages[-1]['content']
 assert run_step.run_step(p,state,cfg) is False and state.email_updated and 'actual body' in email.read_text()
 assert run_step.run_step(p,state,cfg) is True and state.termination_reason=='end_session' and p.phase_tools==[False,True,True]
 saved=json.loads((review.CHECKPOINT_ROOT/'review/messages.json').read_text());assert saved[-1]==message
 records=[json.loads(l) for l in (review.CHECKPOINT_ROOT/'requests.jsonl').read_text().splitlines()]
 assert sum(r['event']=='request' for r in records)==3
 email.write_bytes(original);checks.append({'historical_pseudo_tool_review_'+num+'_full_transition':True})
# Failed native action remains in history and receives a matching error before correction.
p=FakeProvider([call('update_email',{'body':'bad'},'bad'),call('update_email',{'subject':'fixed','body':'fixed'},'fixed'),call('end_session',{},'end')]);state=FundingEmailState()
assert not run_step.run_step(p,state,cfg) and email.read_bytes()==original
assert not run_step.run_step(p,state,cfg) and state.email_updated
assert run_step.run_step(p,state,cfg) and p.invocations==3
assert p.messages[2]['tool_calls'][0]['id']=='bad' and p.messages[3]['tool_call_id']=='bad'
email.write_bytes(original);checks.append({'schema_error_recovery_preserves_history':True})
# Reject parallel calls atomically, including an apparent end_session.
m=call('update_email',{'subject':'bad','body':'bad'},'p1');m['tool_calls']+=call('end_session',{},'p2')['tool_calls']
p=FakeProvider([m]);state=FundingEmailState();assert not run_step.run_step(p,state,cfg)
assert email.read_bytes()==original and not state.termination_reason
assert [x['tool_call_id'] for x in p.messages if x['role']=='tool']==['p1','p2'];checks.append({'parallel_update_end_not_executed':True})
p=FakeProvider([call('update_email',{'subject':'bad','body':'bad'},finish='length')]);state=FundingEmailState()
assert run_step.run_step(p,state,cfg) and state.termination_reason=='truncated_response' and email.read_bytes()==original
checks.append({'truncated_action_not_executed':True})
for name,m,expected in [('wrong_facts',text('Wrong facts; improve the pitch.'),True),('empty',text(''),False),('truncated',text('partial','length'),False),('structured_tool',call('update_email',{'subject':'bad','body':'bad'}),False)]:
 review.CHECKPOINT_ROOT=Path('/opt/output')/('offline_review_'+name);p=FakeProvider([m]);state=FundingEmailState()
 assert review.perform_review(p,state,cfg) is expected and email.read_bytes()==original
 assert p.invocations==1 and p.phase_tools==[False]
 checks.append({name+'_review_handling':True})
Path('/opt/output/offline_controls.json').write_text(json.dumps({'passed':True,'checks':checks},indent=2)+'\n')
print('OFFLINE_CONTROLS_PASSED',json.dumps(checks))
