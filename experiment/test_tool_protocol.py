"""Offline checks for tool boundaries shared by the retained experiments."""
import unittest
from run_upward_documents import InferenceFailure
from tool_protocol import boundary_check, wire


class ToolProtocolTests(unittest.TestCase):
    def test_reasoning_and_structured_calls_survive_history(self):
        calls = [{'id': 'call-1', 'type': 'function',
                  'function': {'name': 'wait', 'arguments': '{"seconds":2}'}}]
        for alias in ('reasoning', 'reasoning_content'):
            message = {'role': 'assistant', 'content': None, alias: 'Planning the next step.',
                       'tool_calls': calls, 'usage': {'completion_tokens': 3}}
            sent = wire([message, {'role': 'tool', 'tool_call_id': 'call-1', 'content': 'Done.'}])
            self.assertEqual(sent[0]['reasoning_content'], message[alias])
            self.assertEqual(sent[0]['tool_calls'], calls)
            self.assertEqual(sent[1]['tool_call_id'], 'call-1')
            self.assertNotIn('usage', sent[0])
            self.assertEqual(message['content'], None)

    def test_conflicting_reasoning_aliases_fail(self):
        with self.assertRaises(InferenceFailure):
            wire([{'role': 'assistant', 'reasoning': 'a', 'reasoning_content': 'b'}])

    def test_pseudo_calls_and_empty_outputs_are_not_completion(self):
        for message in [
            {'role': 'assistant', 'content': ''},
            {'role': 'assistant', 'reasoning': '<tool_call>wait</tool_call>'},
            {'role': 'assistant', 'content': '<function=wait>{}</function>'},
            {'role': 'user', 'content': 'Wrong role'},
        ]:
            with self.assertRaises(InferenceFailure):
                boundary_check(message)
        boundary_check({'role': 'assistant', 'content': 'I cannot complete this task.'})
        boundary_check({'role': 'assistant', 'content': '', 'finish_reason': 'length'})


if __name__ == '__main__':
    unittest.main()
