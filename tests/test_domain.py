import copy
import json
import unittest

from label_workbench.application import ROOT
from label_workbench.domain import run


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((ROOT / 'fixtures/data.json').read_text())
        self.data = {key: [] for key in self.fixture['tables']}

    def test_fixture_is_deterministic_and_not_mutated(self):
        original = copy.deepcopy(self.fixture['tables'])
        options = {'cutoff': self.fixture['meta']['default_cutoff'], 'group': ''}
        first = run(self.fixture['tables'], options)
        second = run(self.fixture['tables'], options)
        self.assertEqual(first, second)
        self.assertEqual(original, self.fixture['tables'])
        self.assertTrue(first['rows'])
        json.dumps(first, allow_nan=False)

    def sample(self):
        self.data['tickets'] = [dict(ticket_id='t', case_id='c', product_line='甲', text='来件', created_at=1)]
        self.data['sources'] = [dict(source='s1', family='f', version='v1', scope=['甲']), dict(source='s2', family='f', version='v1', scope=['甲']), dict(source='s3', family='g', version='v2', scope=['乙'])]
        self.data['votes'] = [dict(ticket_id='t', source='s1', version='v1', label='物流', known_at=1), dict(ticket_id='t', source='s2', version='v1', label='质量', known_at=1), dict(ticket_id='t', source='s3', version='v1', label='其他', known_at=1)]
        self.data['gold'] = [dict(ticket_id='t', label='质量', reviewed_at=8)]

    def test_family_and_scope_are_not_votes_of_truth(self):
        self.sample()
        row = run(self.data, {'cutoff': 4, 'group': ''})['rows'][0]
        self.assertTrue(row['conflict'])
        self.assertEqual(row['families'], ['f'])
        self.assertEqual(set(row['labels']), {'物流', '质量'})
        self.assertIsNone(row['reviewed'])

    def test_abstention_is_not_a_label(self):
        self.sample()
        for vote in self.data['votes']:
            vote['label'] = None
        row = run(self.data, {'cutoff': 4, 'group': ''})['rows'][0]
        self.assertFalse(row['conflict'])
        self.assertEqual(row['labels'], [])
        self.assertEqual(row['abstentions'], 2)

    def test_review_visibility(self):
        self.sample()
        row = run(self.data, {'cutoff': 8, 'group': '甲'})['rows'][0]
        self.assertEqual(row['reviewed'], '质量')
