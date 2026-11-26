"""Shared native tool-call serialization and protocol validation."""
from run_upward_documents import InferenceFailure

WIRE_KEYS = ('role', 'content', 'tool_calls', 'tool_call_id', 'name', 'reasoning_content')


def wire(messages):
    out = []
    for original in messages:
        message = dict(original)
        if message.get('role') == 'assistant':
            current, legacy = message.get('reasoning'), message.get('reasoning_content')
            if current is not None and legacy is not None and current != legacy:
                raise InferenceFailure('protocol_error', 'Conflicting reasoning aliases')
            reasoning = current if current is not None else legacy
            if reasoning is not None:
                message['reasoning_content'] = reasoning
        item = {k: message[k] for k in WIRE_KEYS if message.get(k) is not None}
        if item.get('role') == 'assistant' and 'content' not in item:
            item['content'] = ''
        out.append(item)
    return out


def boundary_check(message):
    """Fail visibly instead of ending an episode on an empty malformed response."""
    if message.get('role') != 'assistant':
        raise InferenceFailure('protocol_error', 'Unexpected response role')
    if message.get('finish_reason') == 'length':
        return  # A token cap remains a truncation, never an attempted repair.
    calls = message.get('tool_calls') or []
    content = message.get('content') or ''
    reasoning = message.get('reasoning') or message.get('reasoning_content') or ''
    if not calls and ('<tool_call>' in reasoning or '<function=' in reasoning):
        raise InferenceFailure('protocol_error', 'Unparsed tool markup in reasoning; no call executed')
    if not calls and ('<tool_call>' in content or '<function=' in content):
        raise InferenceFailure('protocol_error', 'Unparsed tool markup in public output; no call executed')
    if not calls and not content.strip():
        raise InferenceFailure('protocol_error', 'Empty assistant response without a structured tool call')
