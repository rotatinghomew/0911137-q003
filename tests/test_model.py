import copy
import json
import unittest

from label_workbench.application import ROOT
from label_workbench import model


def empty_tables():
    return {'tickets': [], 'sources': [], 'votes': [], 'gold': []}


def vote(family, source, label, version='v1'):
    return {'family': family, 'source': source, 'version': version, 'label': label}


class FamilyOpinionTests(unittest.TestCase):
    def test_shared_keyword_logic_counts_as_one_opinion(self):
        votes = [vote('kw', 'a', '物流'), vote('kw', 'b', '质量'), vote('sup', 'c', '物流')]
        opinions, unknown = model.family_opinions(votes, ['物流', '质量'], {'a': 'v1', 'b': 'v1', 'c': 'v1'})
        self.assertEqual(opinions, {'sup': '物流'})
        self.assertEqual(unknown, [])

    def test_version_mismatch_and_unknown_label_are_excluded(self):
        votes = [vote('kw', 'a', '物流', version='v2'), vote('sup', 'c', '新品类')]
        opinions, unknown = model.family_opinions(votes, ['物流'], {'a': 'v1', 'c': 'v1'})
        self.assertEqual(opinions, {})
        self.assertEqual(unknown, ['新品类'])

    def test_scope_and_current_version_filter_visible_rows(self):
        tables = empty_tables()
        tables['sources'] = [dict(source='s1', family='f', version='v1', scope=['甲']),
                             dict(source='s2', family='g', version='v1', scope=['乙']),
                             dict(source='s3', family='h', version='v2', scope=['甲'])]
        tables['tickets'] = [dict(ticket_id='t', case_id='c', product_line='甲', text='来件', created_at=1)]
        tables['votes'] = [dict(ticket_id='t', source='s1', version='v1', label='物流', known_at=1),
                           dict(ticket_id='t', source='s2', version='v1', label='物流', known_at=1),
                           dict(ticket_id='t', source='s3', version='v1', label='物流', known_at=1)]
        rows = model.visible_rows(tables, {'cutoff': 5, 'group': ''})
        self.assertEqual([entry['source'] for entry in rows[0]['votes']], ['s1'])

    def test_gold_visibility_respects_cutoff(self):
        tables = empty_tables()
        tables['tickets'] = [dict(ticket_id='t', case_id='c', product_line='甲', text='来件', created_at=1)]
        tables['gold'] = [dict(ticket_id='t', label='物流', reviewed_at=8)]
        self.assertIsNone(model.visible_rows(tables, {'cutoff': 4, 'group': ''})[0]['gold'])
        self.assertEqual(model.visible_rows(tables, {'cutoff': 8, 'group': ''})[0]['gold'], '物流')


class DecideTests(unittest.TestCase):
    def trained(self):
        rows = []
        for index in range(4):
            rows.append({'ticket_id': f't{index}', 'case_id': f'c{index}', 'gold': '甲类',
                         'votes': [vote('f1', 's', '甲类' if index < 3 else '乙类')]})
        rows.append({'ticket_id': 't4', 'case_id': 'c4', 'gold': '乙类', 'votes': []})
        return model.train_model(rows, ['甲类', '乙类'], {'s': 'v1'})

    def test_single_family_dependency_goes_to_human(self):
        trained = self.trained()
        scored = model.score(trained, {'f1': '甲类'})
        self.assertGreater(scored['confidence'], 0.6)
        decision = model.decide(model.scheme('balanced'), scored, {'f1': '甲类'}, [])
        self.assertEqual(decision['decision'], 'human')
        self.assertIn('仅单一来源族支持且置信不足', decision['reasons'])

    def test_independent_families_can_auto_decide(self):
        trained = self.trained()
        trained['families']['f2'] = dict(trained['families']['f1'])
        scored = model.score(trained, {'f1': '甲类', 'f2': '甲类'})
        decision = model.decide(model.scheme('balanced'), scored, {'f1': '甲类', 'f2': '甲类'}, [])
        self.assertEqual(decision['decision'], 'auto')
        self.assertEqual(decision['label'], '甲类')

    def test_unknown_label_forces_human(self):
        trained = self.trained()
        scored = model.score(trained, {'f1': '甲类'})
        decision = model.decide(model.scheme('loose'), scored, {'f1': '甲类'}, ['新品类'])
        self.assertEqual(decision['decision'], 'human')
        self.assertTrue(any('未收录标签' in reason for reason in decision['reasons']))


class EvaluationTests(unittest.TestCase):
    def fixture(self):
        tables = empty_tables()
        tables['sources'] = [dict(source='sup', family='sup', version='v1', scope=['甲'])]
        for index in range(6):
            tables['tickets'].append(dict(ticket_id=f'ok{index}', case_id=f'ok{index}', product_line='甲', text='来件', created_at=1))
            tables['votes'].append(dict(ticket_id=f'ok{index}', source='sup', version='v1', label='物流', known_at=1))
            tables['gold'].append(dict(ticket_id=f'ok{index}', label='物流', reviewed_at=1))
        tables['tickets'].append(dict(ticket_id='bad', case_id='bad', product_line='甲', text='来件', created_at=1))
        tables['votes'].append(dict(ticket_id='bad', source='sup', version='v1', label='物流', known_at=1))
        tables['gold'].append(dict(ticket_id='bad', label='罕见', reviewed_at=1))
        tables['tickets'].append(dict(ticket_id='silent', case_id='silent', product_line='甲', text='来件', created_at=1))
        tables['gold'].append(dict(ticket_id='silent', label='罕见', reviewed_at=1))
        return tables

    def report(self, validation, scheme_id):
        return next(item for item in validation['schemes'] if item['id'] == scheme_id)

    def cause(self, report, label):
        return next(item for item in report['causes'] if item['label'] == label)

    def test_per_cause_metrics_expose_rare_cause_misses(self):
        validation = model.evaluate(self.fixture(), {'cutoff': 1, 'group': ''})
        loose = self.report(validation, 'loose')
        self.assertEqual(loose['totals'], {'tickets': 8, 'auto': 7, 'auto_correct': 6, 'auto_wrong': 1, 'human': 1})
        common = self.cause(loose, '物流')
        self.assertEqual((common['support'], common['auto_correct'], common['auto_wrong'], common['to_human']), (6, 6, 0, 0))
        self.assertEqual(common['recall'], 1.0)
        rare = self.cause(loose, '罕见')
        self.assertEqual((rare['support'], rare['auto_correct'], rare['auto_wrong'], rare['to_human']), (2, 0, 1, 1))
        self.assertEqual(rare['recall'], 0.0)
        self.assertEqual(rare['miss'], 0.5)

    def test_empty_auto_is_not_reported_as_zero_accuracy(self):
        validation = model.evaluate(self.fixture(), {'cutoff': 1, 'group': ''})
        cautious = self.report(validation, 'cautious')
        self.assertEqual(cautious['totals']['auto'], 0)
        self.assertEqual(cautious['coverage'], 0.0)
        self.assertIsNone(cautious['accuracy_auto'])
        self.assertEqual(cautious['workload'], 1.0)

    def test_case_isolation_and_determinism(self):
        tables = self.fixture()
        cases = [f'c{index}' for index in range(23)]
        first = model.folds_for(cases, 5)
        self.assertEqual(first, model.folds_for(cases, 5))
        self.assertEqual(sorted(set(first.values())), [0, 1, 2, 3, 4])
        sizes = sorted(first.values()).count
        self.assertTrue(all(4 <= sizes(fold) <= 5 for fold in range(5)))
        original = copy.deepcopy(tables)
        one = model.evaluate(tables, {'cutoff': 1, 'group': ''})
        two = model.evaluate(tables, {'cutoff': 1, 'group': ''})
        self.assertEqual(one, two)
        self.assertEqual(tables, original)
        json.dumps(one, allow_nan=False)
        for report in one['schemes']:
            self.assertEqual(report['totals']['tickets'], 8)
            self.assertEqual(report['totals']['auto'] + report['totals']['human'], 8)

    def test_unknown_labels_are_reported_and_sent_to_human(self):
        tables = empty_tables()
        tables['sources'] = [dict(source='sup', family='sup', version='v1', scope=['甲'])]
        tables['tickets'] = [dict(ticket_id='a', case_id='a', product_line='甲', text='来件', created_at=1),
                             dict(ticket_id='b', case_id='b', product_line='甲', text='来件', created_at=1)]
        tables['votes'] = [dict(ticket_id='a', source='sup', version='v1', label='新品类', known_at=1),
                           dict(ticket_id='b', source='sup', version='v1', label='物流', known_at=1)]
        tables['gold'] = [dict(ticket_id='a', label='物流', reviewed_at=1), dict(ticket_id='b', label='物流', reviewed_at=1)]
        validation = model.evaluate(tables, {'cutoff': 1, 'group': ''})
        self.assertEqual(validation['unknown_vote_labels'], ['新品类'])
        self.assertTrue(any('新品类' in note for note in validation['notes']))
        for report in validation['schemes']:
            self.assertEqual(report['totals']['human'], 1)
            self.assertEqual(self.cause(report, '物流')['to_human'], 1)

    def test_validation_requires_two_isolated_cases(self):
        tables = empty_tables()
        tables['tickets'] = [dict(ticket_id='t', case_id='c', product_line='甲', text='来件', created_at=1)]
        tables['gold'] = [dict(ticket_id='t', label='物流', reviewed_at=1)]
        with self.assertRaises(ValueError):
            model.evaluate(tables, {'cutoff': 1, 'group': ''})


class ReleaseTests(unittest.TestCase):
    def test_release_binds_taxonomy_sources_and_training_scope(self):
        tables = EvaluationTests().fixture()
        trained = model.build_release(tables, {'cutoff': 1, 'group': ''})
        self.assertEqual(trained['taxonomy'], sorted(['物流', '罕见']))
        self.assertEqual(trained['source_versions'], {'sup': 'v1'})
        self.assertEqual(trained['trained'], {'tickets': 8, 'cases': 8})
        self.assertIn('sup', trained['families'])
        json.dumps(trained, allow_nan=False)

    def test_release_requires_reviewed_samples(self):
        with self.assertRaises(ValueError):
            model.build_release(empty_tables(), {'cutoff': 1, 'group': ''})

    def test_suggestion_uses_bound_source_versions(self):
        tables = EvaluationTests().fixture()
        trained = model.build_release(tables, {'cutoff': 1, 'group': ''})
        row = {'ticket_id': 'new', 'case_id': 'new', 'votes': [vote('sup', 'sup', '物流', version='v2')]}
        suggestion = model.suggest_one(trained, 'loose', row)
        self.assertEqual(suggestion['decision'], 'human')
        self.assertIn('无可用来源意见', suggestion['reasons'])

    def test_fixture_pipeline_is_deterministic(self):
        fixture = json.loads((ROOT / 'fixtures/data.json').read_text())
        original = copy.deepcopy(fixture['tables'])
        options = {'cutoff': fixture['meta']['default_cutoff'], 'group': ''}
        validation = model.evaluate(fixture['tables'], options)
        trained = model.build_release(fixture['tables'], options)
        self.assertEqual(fixture['tables'], original)
        self.assertEqual(validation, model.evaluate(fixture['tables'], options))
        self.assertEqual(validation['taxonomy'], trained['taxonomy'])
        self.assertEqual(len(validation['schemes']), 3)
        for report in validation['schemes']:
            self.assertEqual(report['totals']['tickets'], validation['tickets'])
            self.assertTrue(report['causes'])
