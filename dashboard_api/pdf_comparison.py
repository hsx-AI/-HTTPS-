"""Read-only grouping of the latest PDF list and both source snapshots by business code."""
from __future__ import annotations

import json
import sqlite3
from collections import OrderedDict
from contextlib import closing

from .db import SOURCES, resolve_db_path
from .pdf_catalog import latest


def clean(value) -> str:
    return str(value or '').strip()


def uncertain_suffix(code: str, version: str) -> bool:
    return bool(code and version and any(code.endswith(separator + version) and len(code) > len(separator + version) for separator in ('/', '_', '-', '.')))


def owner_rows() -> list[dict]:
    result = []
    for source, label in SOURCES.items():
        path = resolve_db_path(source)
        if not path.exists():
            continue
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            columns = {row[1] for row in conn.execute('PRAGMA table_info(documents)')}
            optional = ', display_code, raw_data' if {'display_code', 'raw_data'} <= columns else ", '' AS display_code, '' AS raw_data"
            for row in conn.execute('SELECT "文件编号", "文件名称", "文件版本", "流程状态"' + optional + ' FROM documents ORDER BY rowid'):
                item = dict(row)
                record_key = clean(item['文件编号'])
                version = clean(item['文件版本'])
                if source == 'ae':
                    code = record_key  # AE export supplies the business number and version separately.
                else:
                    code = clean(item['display_code'])
                    if not code:
                        try:
                            fields = json.loads(item['raw_data'] or '[]')
                            code = next((clean(field.get('value')) for field in fields if field.get('name') == '质量计划编码'), '')
                        except (ValueError, TypeError):
                            pass
                result.append({
                    'source': source, 'sourceLabel': label, 'recordKey': record_key,
                    'name': clean(item['文件名称']), 'originalCode': code, 'version': version,
                    'status': clean(item['流程状态']), 'matchCode': code,
                    'needsReview': not code or (source == 'ae' and uncertain_suffix(code, version)),
                })
    return result


def compare(q: str = '', view: str = '全部', page: int = 1, page_size: int = 20) -> dict:
    pdf = latest(1, 10000)
    if not pdf['batch']:
        return {'hasPdf': False, 'batch': None, 'groups': [], 'total': 0, 'page': page, 'pageSize': page_size}
    groups: OrderedDict[str, dict] = OrderedDict()

    def add(code: str, side: str, row: dict, identity: str) -> None:
        key = code if code else identity
        if key not in groups:
            groups[key] = {'key': key, 'matchCode': code, 'owners': [], 'mine': [], 'needsReview': False}
        groups[key][side].append(row)
        groups[key]['needsReview'] |= row['needsReview']

    for row in pdf['rows']:
        values = row['values']
        code, version = clean(values[2]), clean(values[5])
        item = {
            'name': clean(values[1]), 'originalCode': code, 'internalCode': clean(values[3]),
            'version': version, 'status': clean(values[8]), 'page': row['page'],
            'rowIndex': row['index'], 'needsReview': not code or uncertain_suffix(code, version),
        }
        add(code, 'mine', item, f'missing:mine:{row["index"]}')
    for row in owner_rows():
        add(row['matchCode'], 'owners', row, f'missing:owner:{row["source"]}:{row["recordKey"]}')

    output = []
    for group in groups.values():
        owners, mine = len(group['owners']), len(group['mine'])
        if group['needsReview']:
            category = '待核对'
        elif owners and mine:
            category = '双方都有'
        elif mine:
            category = '仅我方有'
        else:
            category = '仅业主有'
        if owners and mine:
            relation = '一对一' if owners == mine == 1 else '一对多' if mine == 1 else '多对一' if owners == 1 else '多对多'
        else:
            relation = category
        group.update(category=category, relation=relation, ownerCount=owners, mineCount=mine)
        if q.strip() and q.strip() not in group['matchCode']:
            continue
        if view != '全部' and category != view:
            continue
        output.append(group)
    return {'hasPdf': True, 'batch': pdf['batch'], 'groups': output[(page - 1) * page_size:page * page_size],
            'total': len(output), 'page': page, 'pageSize': page_size}


SECTION_KEYS = ('oneToMany', 'otherMatched', 'mineOnly', 'ownerOnly', 'review')


def compare_sections(q: str = '', pages: dict | None = None, page_size: int = 20) -> dict:
    """Three visible buckets plus two expandable lists, with independent pagination."""
    pages = pages or {}
    result = compare(q=q, page=1, page_size=1000000)
    buckets = {key: [] for key in SECTION_KEYS}
    for group in result['groups']:
        if group['category'] == '待核对':
            key = 'review'
        elif group['ownerCount'] and group['mineCount']:
            key = 'oneToMany' if group['mineCount'] == 1 and group['ownerCount'] > 1 else 'otherMatched'
        elif group['mineCount']:
            key = 'mineOnly'
        else:
            key = 'ownerOnly'
        buckets[key].append(group)
    sections = {}
    for key, groups in buckets.items():
        page = max(1, int(pages.get(key, 1)))
        sections[key] = {'total': len(groups), 'page': page, 'pageSize': page_size,
                         'groups': groups[(page - 1) * page_size:page * page_size]}
    return {'hasPdf': result['hasPdf'], 'batch': result['batch'], 'sections': sections}
