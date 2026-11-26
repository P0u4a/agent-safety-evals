"""Exercise document isolation, sampling and control gating without inference."""
import json
from pathlib import Path
import tempfile
import unittest
from run_documents_evaluation import control_gate, offline_preflight
from run_upward_documents import ROOT


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'experiment/configs/upward_documents.json').read_text())

    def test_episode_wiring_and_document_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            offline_preflight(Path(directory), self.config)
            result = json.loads((Path(directory) / 'offline_preflight.json').read_text())
            self.assertTrue(result['passed'])
            self.assertEqual(result['model_requests'], 0)

    def test_healthy_controls_gate_on_evidence_and_accuracy(self):
        records = []
        for case in self.config['cases']:
            for rep in range(case['control_repetitions']):
                records.append({'id': f"{case['id']}-{rep}", 'case_id': case['id'],
                    'environment': case['environment'], 'status': 'completed',
                    'usage': {'missing_usage_turns': 0}, 'healthy_official_text_observed': True,
                    'final_response': case['healthy_control']['expected_answer']})
        self.assertTrue(control_gate(records, self.config)['passed'])
        for record in records:
            record['healthy_official_text_observed'] = False
        self.assertFalse(control_gate(records, self.config)['passed'])


if __name__ == '__main__':
    unittest.main()
