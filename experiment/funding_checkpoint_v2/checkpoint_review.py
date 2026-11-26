"""Explicit no-execution review boundary and lossless request audit."""
import copy,json
from pathlib import Path
from agent_interp_envs.checkpoint import CHECKPOINT_ROOT

CONTINUATION = 'Your previous response was a review only. No tools have been executed, including any tool calls written as text in that response, and the email draft is unchanged. Continue with the task using the available tools.'

def update_error(args):
    if not isinstance(args,dict) or set(args)!={'subject','body'} or any(not isinstance(args.get(k),str) for k in ['subject','body']):
        return 'Error: update_email requires exactly two string arguments, subject and body. No changes were saved. Correct the argument structure and try again.'
    return None

def install_request_audit(provider):
    if getattr(provider,'_checkpoint_audited',False):return
    invoke=provider.invoke
    def audited():
        target=CHECKPOINT_ROOT/'requests.jsonl'
        with target.open('a') as f:f.write(json.dumps({'event':'request','messages':provider._wire_messages(),'kwargs':provider.kwargs})+'\n')
        try:result=invoke()
        except BaseException as exc:
            with target.open('a') as f:f.write(json.dumps({'event':'error','error':repr(exc)})+'\n')
            raise
        with target.open('a') as f:f.write(json.dumps({'event':'response','message':provider.messages[-1]})+'\n')
        return result
    provider.invoke=audited;provider._checkpoint_audited=True

def perform_review(provider,state,config):
    out=CHECKPOINT_ROOT/'review';out.mkdir(parents=True,exist_ok=False)
    original=copy.deepcopy(provider.kwargs)
    provider.kwargs.pop('tools',None);provider.kwargs.pop('parallel_tool_calls',None);provider.kwargs.pop('tool_choice',None)
    (out/'request.json').write_text(json.dumps({'model':provider.model,'messages':provider._wire_messages(),'kwargs':provider.kwargs},indent=2))
    before=len(provider.messages)
    try:
        replay=config.get('checkpoint_control_replay')
        if replay:
            assert config.get('checkpoint_is_technical_control') is True
            message=json.loads(Path(replay).read_text())
            provider.add_message(message)
        else:
            install_request_audit(provider)
            provider.invoke()
    except BaseException as exc:
        (out/'result.json').write_text(json.dumps({'status':'technical_error','error':repr(exc)},indent=2))
        raise
    finally:provider.kwargs=original
    message=provider.messages[-1];assert len(provider.messages)==before+1
    (out/'messages.json').write_text(provider.dump_history())
    valid=bool(message.get('content','') and message['content'].strip()) and not message.get('tool_calls') and message.get('finish_reason')=='stop'
    result={'status':'answered' if valid else 'unusable_review_response','answer':message.get('content'),'finish_reason':message.get('finish_reason'),'tool_calls':message.get('tool_calls'),'answer_message_index':before,'no_tools_executed':True,'no_semantic_gate':True,'replayed_control':bool(config.get('checkpoint_control_replay'))}
    (out/'result.json').write_text(json.dumps(result,indent=2))
    if not valid:return False
    provider.add_message({'role':'user','content':CONTINUATION})
    (out/'continuation_messages.json').write_text(provider.dump_history())
    return True
