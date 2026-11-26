"""Reuse frozen deployment semantics; add Gemma-native malformed-call detection."""
import deployment_episode as implementation
from tool_protocol import boundary_check as original_boundary
from run_upward_documents import InferenceFailure


def boundary_check(message):
    original_boundary(message)
    if message.get('finish_reason') == 'length' or message.get('tool_calls'):
        return
    text = (message.get('content') or '') + (message.get('reasoning') or message.get('reasoning_content') or '')
    if '<|tool_call>' in text or '<tool_call|>' in text:
        raise InferenceFailure('protocol_error', 'Unparsed Gemma tool markup; no call executed')


implementation.boundary_check = boundary_check
episode = implementation.episode
