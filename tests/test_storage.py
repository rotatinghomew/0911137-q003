import copy
import json
from pathlib import Path
import tempfile
import unittest

from label_workbench.application import Application, ROOT
from label_workbench.storage import AnalysisStore, read_dataset


class StorageTests(unittest.TestCase):
    def test_fingerprint_depends_on_source_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'data.json'
            payload = (ROOT / 'fixtures/data.json').read_bytes()
            source.write_bytes(payload)
            original, digest = read_dataset(source)
            source.write_bytes(payload + b'\n')
            same, changed = read_dataset(source)
            self.assertEqual(original, same)
            self.assertNotEqual(digest, changed)

    def test_empty_store_and_unknown_id(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AnalysisStore(Path(directory) / 'data.sqlite3')
            self.assertEqual(store.list(), [])
            with self.assertRaises(KeyError):
                store.get('unknown')

    def test_nonfinite_result_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AnalysisStore(Path(directory) / 'data.sqlite3')
            with self.assertRaises(ValueError):
                store.save('无穷值', 'digest', {}, {'value': float('nan')})
            self.assertEqual(store.list(), [])

    def test_empty_scope_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'data.json'
            data = json.loads((ROOT / 'fixtures/data.json').read_text())
            data['tables'] = {key: [] for key in data['tables']}
            source.write_text(json.dumps(data))
            app = Application(source, Path(directory) / 'state.sqlite3', ROOT / 'web')
            result = app.analyze({})
            self.assertEqual(result['result']['rows'], [])
            self.assertTrue(result['result']['notes'])

    def release_payload(self):
        return ({'cutoff': 30, 'group': ''},
                {'taxonomy': ['物流'], 'source_versions': {'s0': 'v1'}, 'priors': {'物流': 1.0}, 'families': {}},
                {'folds': 2, 'cases': 2, 'tickets': 2, 'schemes': [{'id': 'balanced', 'name': '均衡'}]})

    def test_release_lifecycle_and_single_active(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AnalysisStore(Path(directory) / 'data.sqlite3')
            options, trained, validation = self.release_payload()
            first = store.save_release('版本一', 'digest', options, trained, validation)
            self.assertIsNone(store.active_release())
            self.assertIsNone(store.list_releases()[0]['published_scheme'])
            published = store.publish_release(first['id'], 'balanced')
            self.assertEqual(published['published_scheme'], 'balanced')
            self.assertEqual(store.active_release()['id'], first['id'])
            second = store.save_release('版本二', 'digest', options, trained, validation)
            store.publish_release(second['id'], 'balanced')
            self.assertIsNone(store.get_release(first['id'])['published_scheme'])
            self.assertEqual(store.active_release()['id'], second['id'])
            with self.assertRaises(KeyError):
                store.publish_release('missing', 'balanced')
            with self.assertRaises(KeyError):
                store.get_release('missing')
            with self.assertRaises(ValueError):
                store.save_release('', 'digest', options, trained, validation)

    def test_suggestion_is_written_once_and_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AnalysisStore(Path(directory) / 'data.sqlite3')
            options = {'cutoff': 30, 'group': ''}
            payload = {'label': '物流', 'confidence': 0.9, 'decision': 'auto', 'reasons': [], 'families': ['kw'], 'unknown_labels': []}
            store.save_suggestion('t1', 'r1', 'digest', options, payload)
            changed = dict(payload, label='质量')
            store.save_suggestion('t1', 'r2', 'digest', options, changed)
            kept = store.get_suggestion('t1')
            self.assertEqual(kept['release_id'], 'r1')
            self.assertEqual(kept['payload']['label'], '物流')
            self.assertEqual(set(store.suggestions_for(['t1', 't2'])), {'t1'})
            self.assertEqual(store.suggestions_for([]), {})
            with self.assertRaises(KeyError):
                store.get_suggestion('t2')
