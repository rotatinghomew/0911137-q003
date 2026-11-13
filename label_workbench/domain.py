from collections import Counter, defaultdict
import math
from statistics import mean, median


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('数值必须为有限实数')
    return value


def selected(value, group):
    return not group or value == group


def latest(rows, key, revision, visible, cutoff):
    result = {}
    for row in rows:
        if row[visible] > cutoff:
            continue
        previous = result.get(row[key])
        if previous is None or row[revision] > previous[revision]:
            result[row[key]] = row
    return list(result.values())


def output(rows, summary, notes):
    return {'rows': rows, 'summary': summary, 'notes': notes}


def run(data, options):
    cutoff, group = options['cutoff'], options['group']
    sources = {row['source']: row for row in data['sources']}
    gold = {row['ticket_id']: row for row in data['gold'] if row['reviewed_at'] <= cutoff}
    rows = []
    for ticket in data['tickets']:
        if ticket['created_at'] > cutoff or not selected(ticket['product_line'], group):
            continue
        votes = [row for row in data['votes'] if row['ticket_id'] == ticket['ticket_id'] and row['known_at'] <= cutoff]
        usable = []
        abstain = 0
        for vote in votes:
            source = sources.get(vote['source'])
            if source is None or source['version'] != vote['version'] or ticket['product_line'] not in source['scope']:
                continue
            if vote['label'] is None:
                abstain += 1
            else:
                usable.append(dict(label=vote['label'], source=source['source'], family=source['family']))
        labels = sorted({vote['label'] for vote in usable})
        rows.append(dict(ticket=ticket['ticket_id'], case=ticket['case_id'], text=ticket['text'], labels=labels, conflict=len(labels) > 1, families=sorted({vote['family'] for vote in usable}), abstentions=abstain, reviewed=gold.get(ticket['ticket_id'], {}).get('label')))
    return output(rows, {'工单数': len(rows), '来源冲突': sum(row['conflict'] for row in rows), '人工已核': sum(row['reviewed'] is not None for row in rows)}, ['这里只罗列来源，不把投票当成已确认标签。'])
