"""Offline environment equivalence and protocol/censoring regressions."""
import ast
import copy
import json
from pathlib import Path
import tempfile
import unittest

import agentic_effort as runner
from run_agentic_effort import specification


def response(name=None, args=None, final='Unable to complete the transfer.', finish=None):
    m = {'role': 'assistant', 'content': None if name else final, 'reasoning': 'Synthetic audit trace.'}
    if name:
        m['tool_calls'] = [{'id': 'call', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args or {})}}]
    return {'choices': [{'message': m, 'finish_reason': finish or ('tool_calls' if name else 'stop')}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 10}}


class EffortTests(unittest.TestCase):
    def setUp(self):
        self.config, self.jobs, self.controls = specification()
        self.job = next(j for j in self.jobs if j['kind'] == 'agentic' and j['outcome'] == 'unicef')

    def test_source_environment_equivalence_all_conditions(self):
        # Execute the unmodified released module with a minimal import shim in a
        # private builtins scope. Compare with adapter's AST import replacement.
        import builtins
        import types
        original_import = builtins.__import__
        def shim(name, *args, **kwargs):
            return types.SimpleNamespace(ToolDefinition=runner.ToolDefinition) if name == 'localrouter' else original_import(name, *args, **kwargs)
        ns = {'__name__': runner.__name__, '__builtins__': {**vars(builtins), '__import__': shim}}
        p = runner.UPSTREAM / 'agentic_eval/tools.py'
        exec(compile(p.read_text(), str(p), 'exec'), ns)
        cfg = self.config['environment']
        for outcome in [*cfg['targets'], 'choose']:
            for sample in [0, 49]:
                job = {'outcome': outcome, 'sample': sample}
                adapted = runner.environment(job, self.config)
                original = ns['build_env'](outcome, sample, cfg['targets'].get(outcome), cfg['targets'],
                    cfg['dummy_addresses'], cfg['transient_error_messages'], cfg['send_error_messages'], cfg['balance_btc'])
                self.assertEqual(adapted.address_book, original.address_book)
                for name in ['show_balance', 'list_addresses', 'send_btc', 'wait'] * 10:
                    args = {'amount_btc': 0.01, 'recipient_wallet': 'fake', 'seconds': 2}
                    self.assertEqual(runner.UPSTREAM_TOOLS['execute_tool'](name, args, adapted), ns['execute_tool'](name, args, original))
        self.assertEqual([(t.name, t.description, t.input_schema) for t in ns['TOOLS']],
                         [(t['function']['name'], t['function']['description'], t['function']['parameters']) for t in runner.TOOLS])

    def test_design_and_history_roundtrip(self):
        self.assertEqual(len(self.jobs), 1700)
        self.assertEqual(len({j['id'] for j in self.jobs}), 1700)
        self.assertEqual(len(self.controls), 10)
        requests = []
        def transport(payload, *_):
            requests.append(copy.deepcopy(payload))
            for key in ('temperature', 'top_p', 'top_k', 'min_p', 'repetition_penalty', 'max_tokens'):
                self.assertEqual(payload[key], self.config['sampling'][key])
            if len(requests) == 1:
                return response('send_btc', {'amount_btc': 0.01, 'recipient_wallet': 'fake'})
            self.assertEqual(payload['messages'][1]['reasoning_content'], 'Synthetic audit trace.')
            self.assertEqual(payload['messages'][-1]['role'], 'tool')
            self.assertIn(payload['messages'][-1]['content'], self.config['environment']['send_error_messages'])
            return response()
        with tempfile.TemporaryDirectory() as temp:
            r = runner.episode(self.job, self.config, Path(temp), 'http://unused', transport)
        self.assertEqual((r['status'], r['n_send_attempts'], r['n_successful_sends']), ('completed', 1, 0))

    def test_censoring_and_malformed_calls_are_not_voluntary_stopping(self):
        config = copy.deepcopy(self.config)
        config['environment']['safety_cap_turns'] = 2
        malformed = response()
        malformed['choices'][0]['message'].update(content='', reasoning='<tool_call>send_btc</tool_call>')
        for raw, expected in [(response('wait', {'seconds': 1}), 'turn_capped'),
                              (response(final='', finish='length'), 'truncated'), (malformed, 'protocol_error')]:
            with tempfile.TemporaryDirectory() as temp:
                r = runner.episode(self.job, config, Path(temp), 'http://unused', lambda *a: raw)
            self.assertEqual(r['status'], expected)
        self.assertIsNone(runner.ratings('I will not rate this. 50 would be neutral.')['strict'])
        self.assertEqual(runner.ratings('50'), {'strict': 50, 'upstream': 50})

    def test_controls_reject_no_call_and_missing_usage(self):
        job = next(j for j in self.controls if j.get('expected_tool') == 'wait')
        calls = iter([response('wait', {'seconds': 2}), response(final='Waited 2 seconds.')])
        with tempfile.TemporaryDirectory() as temp:
            r = runner.episode(job, self.config, Path(temp), 'http://unused', lambda *a: next(calls))
        self.assertTrue(runner.control_gate([job], [r])['passed'])
        for mutation in [{'status': 'truncated'}, {'tool_counts': {}}, {'usage': {'missing_usage_turns': 1}}]:
            bad = {**r, **mutation}
            self.assertFalse(runner.control_gate([job], [bad])['passed'])


if __name__ == '__main__':
    unittest.main()
