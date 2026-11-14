from collections import Counter, defaultdict
import hashlib
import math

from .domain import selected

SEED = 'after-sales-attribution-v1'
MAX_FOLDS = 5
WEIGHT_CLIP = 3.0

# 候选方案：tau 是最低置信度，margin 是前二标签最小差距，
# single_family_tau 是仅单一来源族支持时要求的更高置信度。
SCHEMES = [
    {'id': 'cautious', 'name': '谨慎', 'tau': 0.8, 'margin': 0.3, 'single_family_tau': 0.95},
    {'id': 'balanced', 'name': '均衡', 'tau': 0.6, 'margin': 0.2, 'single_family_tau': 0.85},
    {'id': 'loose', 'name': '宽松', 'tau': 0.45, 'margin': 0.1, 'single_family_tau': 0.7},
]


def scheme(scheme_id):
    for config in SCHEMES:
        if config['id'] == scheme_id:
            return config
    raise KeyError('未知候选方案')


def visible_rows(tables, options):
    """按分析时点与业务范围取出工单，以及各工单当前可用的来源标签。

    与来源罗列口径一致：来源版本须与当前资料一致，且工单产品线在来源覆盖范围内。
    """
    cutoff, group = options['cutoff'], options['group']
    sources = {row['source']: row for row in tables['sources']}
    gold = {row['ticket_id']: row['label'] for row in tables['gold'] if row['reviewed_at'] <= cutoff}
    votes = defaultdict(list)
    for vote in tables['votes']:
        if vote['known_at'] <= cutoff:
            votes[vote['ticket_id']].append(vote)
    rows = []
    for ticket in tables['tickets']:
        if ticket['created_at'] > cutoff or not selected(ticket['product_line'], group):
            continue
        usable = []
        for vote in votes.get(ticket['ticket_id'], []):
            source = sources.get(vote['source'])
            if source is None or source['version'] != vote['version'] or ticket['product_line'] not in source['scope']:
                continue
            usable.append({'family': source['family'], 'source': vote['source'], 'version': vote['version'], 'label': vote['label']})
        rows.append({'ticket_id': ticket['ticket_id'], 'case_id': ticket['case_id'], 'product_line': ticket['product_line'], 'gold': gold.get(ticket['ticket_id']), 'votes': usable})
    return rows


def family_opinions(votes, taxonomy, source_versions):
    """把来源标签归并为来源族意见；同族共享实现，一族只算一份意见。

    族内标签并列时该族弃权。版本与发布绑定不一致的来源不参与；
    分类集合之外的标签单独返回，不进入意见。
    """
    by_family = defaultdict(Counter)
    unknown = set()
    for vote in votes:
        if source_versions.get(vote['source']) != vote['version'] or vote['label'] is None:
            continue
        if vote['label'] not in taxonomy:
            unknown.add(vote['label'])
            continue
        by_family[vote['family']][vote['label']] += 1
    opinions = {}
    for family, counts in by_family.items():
        (label, amount), *rest = counts.most_common(2)
        if rest and rest[0][1] == amount:
            continue
        opinions[family] = label
    return opinions, sorted(unknown)


def train_model(rows, taxonomy, source_versions):
    """用复核标签估计各来源族可靠度与标签先验；rows 须为已复核工单。"""
    priors = {label: 1 for label in taxonomy}
    families = {}
    for row in rows:
        priors[row['gold']] += 1
        opinions, _ = family_opinions(row['votes'], taxonomy, source_versions)
        for family, label in opinions.items():
            stats = families.setdefault(family, {'correct': 0, 'total': 0})
            stats['total'] += 1
            if label == row['gold']:
                stats['correct'] += 1
    total = sum(priors.values())
    model = {'taxonomy': list(taxonomy), 'source_versions': dict(source_versions),
             'priors': {label: count / total for label, count in priors.items()}, 'families': {}}
    for family, stats in sorted(families.items()):
        reliability = (stats['correct'] + 1) / (stats['total'] + 2)
        weight = math.log(reliability / (1 - reliability))
        model['families'][family] = {**stats, 'reliability': reliability, 'weight': max(-WEIGHT_CLIP, min(WEIGHT_CLIP, weight))}
    return model


def score(model, opinions):
    """按族意见加权打分并归一化；返回头部标签、置信度与前二差距。"""
    logp = {label: math.log(model['priors'][label]) for label in model['taxonomy']}
    for family, label in opinions.items():
        logp[label] += model['families'].get(family, {}).get('weight', 0.0)
    peak = max(logp.values())
    normal = sum(math.exp(value - peak) for value in logp.values())
    probs = {label: math.exp(value - peak) / normal for label, value in logp.items()}
    ranking = sorted(probs.items(), key=lambda item: (-item[1], item[0]))
    label, confidence = ranking[0]
    margin = confidence - (ranking[1][1] if len(ranking) > 1 else 0.0)
    return {'label': label, 'confidence': confidence, 'margin': margin}


def decide(config, scored, opinions, unknown):
    """不确定或来源互相依赖的工单留给人工；reasons 说明转人工的原因。"""
    reasons = []
    if unknown:
        reasons.append('来源提出未收录标签：' + '、'.join(unknown))
    if not opinions:
        reasons.append('无可用来源意见')
    elif len(opinions) < 2 and scored['confidence'] < config['single_family_tau']:
        reasons.append('仅单一来源族支持且置信不足')
    if scored['confidence'] < config['tau']:
        reasons.append('置信度不足')
    if scored['margin'] < config['margin']:
        reasons.append('前二标签差距不足')
    if reasons:
        return {'decision': 'human', 'label': scored['label'], 'reasons': reasons}
    return {'decision': 'auto', 'label': scored['label'], 'reasons': []}


def folds_for(cases, count):
    """按售后事件确定性分组；同一事件的重复来件只落在同一折。"""
    ordered = sorted(cases, key=lambda case: hashlib.sha256(f'{SEED}:{case}'.encode()).hexdigest())
    return {case: index % count for index, case in enumerate(ordered)}


def evaluate(tables, options):
    """分组交叉验证各候选方案，按原因报告自动正确、误判与人工工作量。"""
    rows = visible_rows(tables, options)
    reviewed = [row for row in rows if row['gold'] is not None]
    taxonomy = sorted({row['gold'] for row in reviewed})
    cases = sorted({row['case_id'] for row in reviewed})
    if len(cases) < 2:
        raise ValueError('复核样本覆盖的售后事件不足两个，无法在隔离重复来件的前提下验证')
    fold_count = min(MAX_FOLDS, len(cases))
    assignment = folds_for(cases, fold_count)
    source_versions = {row['source']: row['version'] for row in tables['sources']}
    unknown_labels = sorted({vote['label'] for row in rows for vote in row['votes'] if vote['label'] is not None and vote['label'] not in taxonomy})
    reports = []
    for config in SCHEMES:
        reports.append({'id': config['id'], 'name': config['name'],
                        'params': {'tau': config['tau'], 'margin': config['margin'], 'single_family_tau': config['single_family_tau']},
                        'totals': {'tickets': 0, 'auto': 0, 'auto_correct': 0, 'auto_wrong': 0, 'human': 0},
                        'causes': {label: {'support': 0, 'auto_correct': 0, 'auto_wrong': 0, 'to_human': 0} for label in taxonomy}})
    for fold in range(fold_count):
        train_rows = [row for row in reviewed if assignment[row['case_id']] != fold]
        valid_rows = [row for row in reviewed if assignment[row['case_id']] == fold]
        if not train_rows or not valid_rows:
            continue
        fold_model = train_model(train_rows, taxonomy, source_versions)
        for row in valid_rows:
            opinions, unknown = family_opinions(row['votes'], taxonomy, source_versions)
            scored = score(fold_model, opinions)
            for config, report in zip(SCHEMES, reports):
                decision = decide(config, scored, opinions, unknown)
                totals = report['totals']
                totals['tickets'] += 1
                cause = report['causes'][row['gold']]
                cause['support'] += 1
                if decision['decision'] == 'auto':
                    totals['auto'] += 1
                    if decision['label'] == row['gold']:
                        totals['auto_correct'] += 1
                        cause['auto_correct'] += 1
                    else:
                        totals['auto_wrong'] += 1
                        cause['auto_wrong'] += 1
                else:
                    totals['human'] += 1
                    cause['to_human'] += 1
    for report in reports:
        totals = report['totals']
        report['coverage'] = totals['auto'] / totals['tickets'] if totals['tickets'] else None
        report['accuracy_auto'] = totals['auto_correct'] / totals['auto'] if totals['auto'] else None
        report['workload'] = totals['human'] / totals['tickets'] if totals['tickets'] else None
        report['causes'] = [
            {'label': label, **stats,
             'recall': stats['auto_correct'] / stats['support'] if stats['support'] else None,
             'miss': stats['auto_wrong'] / stats['support'] if stats['support'] else None}
            for label, stats in sorted(report['causes'].items())]
    notes = [f'按售后事件隔离为 {fold_count} 折交叉验证，同一事件的重复来件不会同时出现在训练与验证两侧。',
             '版本分类取自训练时点的复核标签：' + '、'.join(taxonomy) + '。',
             '复核样本有限，请按原因查看支持数与误判，不要只看总体准确率。']
    if unknown_labels:
        notes.append('来源标签 ' + '、'.join(unknown_labels) + ' 不在本次复核分类中，相关工单一律转人工。')
    return {'folds': fold_count, 'cases': len(cases), 'tickets': len(reviewed), 'taxonomy': taxonomy,
            'unknown_vote_labels': unknown_labels, 'schemes': reports, 'notes': notes}


def build_release(tables, options):
    """验证通过后，用全部可见复核样本训练发布模型，并绑定来源版本与分类。"""
    rows = visible_rows(tables, options)
    reviewed = [row for row in rows if row['gold'] is not None]
    taxonomy = sorted({row['gold'] for row in reviewed})
    if not taxonomy:
        raise ValueError('当前范围没有可用的复核样本')
    source_versions = {row['source']: row['version'] for row in tables['sources']}
    model = train_model(reviewed, taxonomy, source_versions)
    model['trained'] = {'tickets': len(reviewed), 'cases': len({row['case_id'] for row in reviewed})}
    return model


def suggest_one(model, scheme_id, row):
    """对一张未复核工单给出建议；决定为 human 时该单留给人工。"""
    config = scheme(scheme_id)
    opinions, unknown = family_opinions(row['votes'], model['taxonomy'], model['source_versions'])
    scored = score(model, opinions)
    decision = decide(config, scored, opinions, unknown)
    return {'ticket': row['ticket_id'], 'case': row['case_id'], 'label': decision['label'],
            'confidence': round(scored['confidence'], 4), 'decision': decision['decision'],
            'reasons': decision['reasons'], 'families': sorted(opinions), 'unknown_labels': unknown}
