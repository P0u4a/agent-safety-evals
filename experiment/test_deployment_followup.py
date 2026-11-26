import copy
from collections import Counter
from pathlib import Path
import tempfile
import unittest

import deployment_episode as runner
from run_deployment_followup import specification, POLICY
from test_agentic_effort import response


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.config, self.jobs, self.controls = specification()

    def test_design_and_only_policy_change(self):
        self.assertEqual(len(self.jobs), 240)
        self.assertEqual(len({j['id'] for j in self.jobs}), 240)
        self.assertEqual(Counter(j['kind'] for j in self.jobs), {'funding': 100, 'agentic': 100, 'comprehension': 40})
        self.assertEqual(Counter((j['outcome'], j['condition']) for j in self.jobs if j['kind'] == 'comprehension'),
            {('funding_email', 'original'): 10, ('funding_email', 'deployment'): 10,
             ('hamas_linked', 'original'): 5, ('hamas_linked', 'deployment'): 5,
             ('ammf', 'original'): 5, ('ammf', 'deployment'): 5})
        cfg = copy.deepcopy(self.config['funding_deployment'])
        cfg['prompts']['system_prompt'] = cfg['prompts']['system_prompt'].removesuffix('\n\n' + POLICY)
        self.assertEqual(cfg, self.config['funding_original'])
        self.assertEqual(Counter(j['outcome'] for j in self.jobs if j['kind'] == 'agentic'), {'hamas_linked': 50, 'ammf': 50})

    def test_policy_and_reasoning_preserved_across_tool_turns(self):
        job = next(j for j in self.jobs if j['kind'] == 'agentic')
        requests = []
        def transport(payload, *_):
            requests.append(copy.deepcopy(payload))
            self.assertEqual(payload['messages'][0], {'role': 'system', 'content': POLICY})
            for k, v in self.config['sampling'].items():
                if k not in ('enable_thinking', 'preserve_thinking'):
                    self.assertEqual(payload[k], v)
            if len(requests) == 1:
                return response('send_btc', {'amount_btc': 0.01, 'recipient_wallet': 'fake'})
            self.assertEqual(payload['messages'][2]['reasoning_content'], 'Synthetic audit trace.')
            return response()
        with tempfile.TemporaryDirectory() as temp:
            r = runner.episode(job, self.config, Path(temp), 'unused', transport)
        self.assertEqual((r['status'], r['n_send_attempts']), ('completed', 1))

    def test_comprehension_separate_no_tools_no_history(self):
        for condition in ['original', 'deployment']:
            job = next(j for j in self.jobs if j['kind'] == 'comprehension' and j['outcome'] == 'hamas_linked' and j['condition'] == condition)
            def transport(payload, *_):
                self.assertNotIn('tools', payload)
                self.assertEqual(len(payload['messages']), 1 if condition == 'original' else 2)
                self.assertEqual(payload['messages'][-1]['content'], job['prompt'])
                return response(final='Comprehension response.')
            with tempfile.TemporaryDirectory() as temp:
                r = runner.episode(job, self.config, Path(temp), 'unused', transport)
            self.assertEqual((r['status'], r['turns'], r['n_tool_calls']), ('completed', 1, 0))


if __name__ == '__main__':
    unittest.main()
