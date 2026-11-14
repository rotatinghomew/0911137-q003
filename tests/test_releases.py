import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from label_workbench.application import Application, ROOT, server


class ReleaseFlowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.application = Application(ROOT / 'fixtures/data.json', Path(self.directory.name) / 'state.sqlite3', ROOT / 'web')
        self.httpd = server(self.application)
        self.worker = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.worker.start()
        self.base = f'http://127.0.0.1:{self.httpd.server_port}'

    def tearDown(self):
        self.httpd.shutdown()
        self.worker.join()
        self.httpd.server_close()
        self.directory.cleanup()

    def get(self, path):
        with urlopen(self.base + path) as response:
            return json.load(response)

    def post(self, path, payload):
        request = Request(self.base + path, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        with urlopen(request) as response:
            return response.status, json.load(response)

    def train(self, name, cutoff=30):
        status, release = self.post('/api/releases', {'name': name, 'options': {'cutoff': cutoff, 'group': ''}})
        self.assertEqual(status, 201)
        return release

    def test_train_validate_publish_suggest_roundtrip(self):
        release = self.train('流程核对')
        self.assertEqual(release['validation']['taxonomy'], ['描述不符', '物流'])
        self.assertEqual(len(release['validation']['schemes']), 3)
        for report in release['validation']['schemes']:
            self.assertEqual(report['totals']['tickets'], release['validation']['tickets'])
            self.assertTrue(report['causes'])
        self.assertEqual(release['model']['source_versions'], {'s0': 'v1', 's1': 'v1', 's2': 'v1', 's3': 'v1', 's4': 'v1'})
        entries = self.get('/api/releases')
        self.assertEqual(len(entries), 1)
        self.assertIsNone(entries[0]['published_scheme'])
        with self.assertRaises(HTTPError) as caught:
            self.get('/api/suggestions')
        self.assertEqual(caught.exception.code, 400)
        status, published = self.post(f"/api/releases/{release['id']}/publish", {'scheme': 'balanced'})
        self.assertEqual(status, 200)
        self.assertEqual(published['published_scheme'], 'balanced')
        suggestions = self.get('/api/suggestions?cutoff=30')
        self.assertEqual(suggestions['release']['id'], release['id'])
        self.assertTrue(suggestions['rows'])
        summary = suggestions['summary']
        self.assertEqual(summary['待建议工单'], summary['自动建议'] + summary['转人工'])
        self.assertEqual(summary['沿用历史解释'], 0)
        again = self.get('/api/suggestions?cutoff=30')
        self.assertEqual(again['rows'], suggestions['rows'])
        self.assertEqual(again['summary']['沿用历史解释'], summary['待建议工单'])

    def test_old_explanations_survive_new_release(self):
        first = self.train('旧版本', cutoff=10)
        self.post(f"/api/releases/{first['id']}/publish", {'scheme': 'balanced'})
        early = self.get('/api/suggestions?cutoff=10')
        self.assertTrue(early['rows'])
        second = self.train('新版本')
        self.post(f"/api/releases/{second['id']}/publish", {'scheme': 'loose'})
        later = self.get('/api/suggestions?cutoff=30')
        kept = {row['ticket'] for row in early['rows']}
        for row in later['rows']:
            expected = '旧版本' if row['ticket'] in kept else '新版本'
            self.assertEqual(row['release'], expected)
        self.assertEqual(later['summary']['沿用历史解释'], len(kept))
        self.assertEqual(self.get('/api/releases')[1]['published_scheme'], None)

    def test_release_is_frozen_after_save(self):
        first = self.train('第一版')
        before = self.get(f"/api/releases/{first['id']}")
        self.train('第二版')
        after = self.get(f"/api/releases/{first['id']}")
        self.assertEqual(before, after)

    def test_invalid_requests(self):
        release = self.train('有效')
        for path, payload, code in [
            ('/api/releases', {'name': '坏时点', 'options': {'cutoff': 1.5}}, 400),
            ('/api/releases', {'name': '多余字段', 'options': {}, 'extra': 1}, 400),
            ('/api/releases', {'name': '样本不足', 'options': {'cutoff': 1}}, 400),
            (f"/api/releases/{release['id']}/publish", {'scheme': 'missing'}, 400),
            (f"/api/releases/{release['id']}/publish", {'scheme': 'balanced', 'extra': 1}, 400),
            ('/api/releases/missing/publish', {'scheme': 'balanced'}, 404),
            ('/api/releases/missing', None, 404),
        ]:
            if payload is None:
                with self.assertRaises(HTTPError) as caught:
                    self.get(path)
            else:
                with self.assertRaises(HTTPError) as caught:
                    self.post(path, payload)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(len(self.get('/api/releases')), 1)

    def test_group_filter_trains_on_subset(self):
        release = self.train('仅家居', cutoff=30)
        status, _ = self.post(f"/api/releases/{release['id']}/publish", {'scheme': 'balanced'})
        self.assertEqual(status, 200)
        query = urlencode({'cutoff': 30, 'group': '家居'})
        suggestions = self.get('/api/suggestions?' + query)
        self.assertTrue(suggestions['rows'])
        tickets = {row['ticket_id']: row for row in json.loads((ROOT / 'fixtures/data.json').read_text())['tables']['tickets']}
        for row in suggestions['rows']:
            self.assertEqual(tickets[row['ticket']]['product_line'], '家居')
