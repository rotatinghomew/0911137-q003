import hashlib
import json
from pathlib import Path
import sqlite3
import uuid
from datetime import datetime, timezone


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':'))


def read_dataset(path):
    payload = Path(path).read_bytes()
    data = json.loads(payload)
    if not isinstance(data, dict) or not isinstance(data.get('tables'), dict):
        raise ValueError('资料必须包含 tables 对象')
    for name, rows in data['tables'].items():
        if not isinstance(rows, list):
            raise ValueError(f'资料表 {name} 必须为列表')
    return data, hashlib.sha256(payload).hexdigest()


class AnalysisStore:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS analyses (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, digest TEXT NOT NULL, options TEXT NOT NULL, result TEXT NOT NULL)')
            connection.execute('CREATE TABLE IF NOT EXISTS releases (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL, digest TEXT NOT NULL, options TEXT NOT NULL, model TEXT NOT NULL, validation TEXT NOT NULL, published_scheme TEXT)')
            connection.execute('CREATE TABLE IF NOT EXISTS suggestions (ticket_id TEXT PRIMARY KEY, release_id TEXT NOT NULL, digest TEXT NOT NULL, options TEXT NOT NULL, computed_at TEXT NOT NULL, payload TEXT NOT NULL)')

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def save(self, title, digest, options, result):
        if not isinstance(title, str) or not title.strip() or len(title) > 100:
            raise ValueError('分析名称须为一到一百个字符')
        identifier = uuid.uuid4().hex
        created = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute('INSERT INTO analyses VALUES (?, ?, ?, ?, ?, ?)', (identifier, title.strip(), created, digest, encode(options), encode(result)))
        return self.get(identifier)

    def get(self, identifier):
        with self.connect() as connection:
            row = connection.execute('SELECT * FROM analyses WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise KeyError('分析版本不存在')
        return {**dict(row), 'options': json.loads(row['options']), 'result': json.loads(row['result'])}

    def list(self):
        with self.connect() as connection:
            return [dict(row) for row in connection.execute('SELECT id,title,created_at,digest FROM analyses ORDER BY created_at DESC,id')]

    def save_release(self, name, digest, options, model, validation):
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError('版本名称须为一到一百个字符')
        identifier = uuid.uuid4().hex
        created = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute('INSERT INTO releases VALUES (?, ?, ?, ?, ?, ?, ?, NULL)', (identifier, name.strip(), created, digest, encode(options), encode(model), encode(validation)))
        return self.get_release(identifier)

    def decode_release(self, row):
        return {**dict(row), 'options': json.loads(row['options']), 'model': json.loads(row['model']), 'validation': json.loads(row['validation'])}

    def get_release(self, identifier):
        with self.connect() as connection:
            row = connection.execute('SELECT * FROM releases WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise KeyError('原因识别版本不存在')
        return self.decode_release(row)

    def list_releases(self):
        with self.connect() as connection:
            rows = connection.execute('SELECT * FROM releases ORDER BY created_at DESC,id').fetchall()
        entries = []
        for row in rows:
            release = self.decode_release(row)
            entries.append({'id': release['id'], 'name': release['name'], 'created_at': release['created_at'], 'digest': release['digest'],
                            'published_scheme': release['published_scheme'], 'taxonomy': release['model']['taxonomy'],
                            'schemes': [{'id': item['id'], 'name': item['name']} for item in release['validation']['schemes']]})
        return entries

    def active_release(self):
        with self.connect() as connection:
            row = connection.execute('SELECT * FROM releases WHERE published_scheme IS NOT NULL').fetchone()
        return None if row is None else self.decode_release(row)

    def publish_release(self, identifier, scheme):
        with self.connect() as connection:
            if connection.execute('SELECT 1 FROM releases WHERE id=?', (identifier,)).fetchone() is None:
                raise KeyError('原因识别版本不存在')
            connection.execute('UPDATE releases SET published_scheme=NULL')
            connection.execute('UPDATE releases SET published_scheme=? WHERE id=?', (scheme, identifier))
        return self.get_release(identifier)

    def decode_suggestion(self, row):
        return {**dict(row), 'options': json.loads(row['options']), 'payload': json.loads(row['payload'])}

    def get_suggestion(self, ticket_id):
        with self.connect() as connection:
            row = connection.execute('SELECT * FROM suggestions WHERE ticket_id=?', (ticket_id,)).fetchone()
        if row is None:
            raise KeyError('工单建议不存在')
        return self.decode_suggestion(row)

    def suggestions_for(self, ticket_ids):
        if not ticket_ids:
            return {}
        marks = ','.join('?' * len(ticket_ids))
        with self.connect() as connection:
            rows = connection.execute(f'SELECT * FROM suggestions WHERE ticket_id IN ({marks})', list(ticket_ids)).fetchall()
        return {row['ticket_id']: self.decode_suggestion(row) for row in rows}

    def save_suggestion(self, ticket_id, release_id, digest, options, payload):
        created = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute('INSERT OR IGNORE INTO suggestions VALUES (?, ?, ?, ?, ?, ?)', (ticket_id, release_id, digest, encode(options), created, encode(payload)))
        return self.get_suggestion(ticket_id)
