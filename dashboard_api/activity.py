"""Dashboard-owned quality-plan activity, stored outside replaced source snapshots."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from .db import SOURCES, active_source, resolve_db_path

WINDOW_DAYS = 7
KIND_LABELS = {
    'added': '新增',
    'process': '流程变更',
    'status': '状态变更',
    'review': '审查评论变更',
}


def activity_path() -> Path:
    raw = os.environ.get('PLAN_ACTIVITY_PATH', '').strip()
    if raw:
        path = Path(raw)
        return path if path.is_absolute() else resolve_db_path().parent / path
    return resolve_db_path().parent / 'quality_plan_activity.db'


def log(message: str) -> None:
    print(f'[动态] {message}', file=sys.stderr, flush=True)


def text(value) -> str:
    return '' if value is None else str(value).strip()


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS plan_activity (
            id INTEGER PRIMARY KEY,
            detected_at TEXT NOT NULL,
            source_id TEXT NOT NULL,
            source_label TEXT NOT NULL,
            record_key TEXT NOT NULL,
            display_code TEXT NOT NULL,
            name TEXT NOT NULL,
            project TEXT NOT NULL DEFAULT '',
            unit TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL,
            old_value TEXT NOT NULL DEFAULT '',
            new_value TEXT NOT NULL DEFAULT '',
            sync_batch_id TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute('CREATE INDEX IF NOT EXISTS idx_plan_activity_detected ON plan_activity (detected_at DESC, id DESC)')


def _raw_fields(raw_data) -> list[dict]:
    if not raw_data:
        return []
    try:
        payload = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
    except (TypeError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def cgn_status(row: dict) -> str:
    mapped = text(row.get('流程状态'))
    for field in _raw_fields(row.get('raw_data')):
        if field.get('name') == '状态':
            return text(field.get('value'))
    return mapped


def cgn_review_comment(row: dict) -> str:
    for field in _raw_fields(row.get('raw_data')):
        if field.get('name') == '审查评论' or field.get('label') == '审查评论':
            return text(field.get('value'))
    return ''


def display_code_of(row: dict) -> str:
    code = text(row.get('display_code')) or text(row.get('文件编号'))
    version = text(row.get('文件版本'))
    if version and text(row.get('display_code')):
        return f'{code} / {version}'
    return code


def load_documents(path: Path) -> dict[str, dict]:
    records = {}
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        for raw in conn.execute('SELECT * FROM documents'):
            row = dict(raw)
            key = text(row.get('文件编号'))
            if key:
                records[key] = row
    return records


def diff_snapshots(source: str, old_path: Path, new_path: Path, detected_at: str, sync_batch_id: str = '') -> list[dict]:
    if source not in SOURCES:
        raise ValueError('不支持的数据平台')
    old_rows = load_documents(old_path)
    new_rows = load_documents(new_path)
    label = SOURCES[source]
    events = []

    def event(row: dict, kind: str, old_value: str = '', new_value: str = '') -> dict:
        return {
            'detected_at': detected_at,
            'source_id': source,
            'source_label': label,
            'record_key': text(row.get('文件编号')),
            'display_code': display_code_of(row),
            'name': text(row.get('文件名称')),
            'project': text(row.get('所属项目')),
            'unit': text(row.get('适用机组号')),
            'kind': kind,
            'old_value': old_value,
            'new_value': new_value,
            'sync_batch_id': sync_batch_id,
        }

    for key, row in new_rows.items():
        previous = old_rows.get(key)
        if previous is None:
            events.append(event(row, 'added'))
            continue
        if source == 'ae':
            before, after = text(previous.get('流程状态')), text(row.get('流程状态'))
            if before != after:
                events.append(event(row, 'process', before, after))
            continue
        before_status, after_status = cgn_status(previous), cgn_status(row)
        if before_status != after_status:
            events.append(event(row, 'status', before_status, after_status))
        before_review, after_review = cgn_review_comment(previous), cgn_review_comment(row)
        if before_review != after_review:
            events.append(event(row, 'review', before_review, after_review))
    return events


def save_events(events: list[dict]) -> int:
    if not events:
        return 0
    path = activity_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn, conn:
        ensure_schema(conn)
        conn.executemany(
            """
            INSERT INTO plan_activity (
                detected_at, source_id, source_label, record_key, display_code, name,
                project, unit, kind, old_value, new_value, sync_batch_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [[
                item['detected_at'], item['source_id'], item['source_label'], item['record_key'],
                item['display_code'], item['name'], item['project'], item['unit'], item['kind'],
                item['old_value'], item['new_value'], item['sync_batch_id'],
            ] for item in events],
        )
    return len(events)


def list_recent(project: str = '全部', group: str = '全部', days: int = WINDOW_DAYS) -> list[dict]:
    path = activity_path()
    if not path.exists():
        return []
    selected = active_source.get()
    cutoff = (datetime.now().astimezone() - timedelta(days=days)).isoformat(timespec='seconds')
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='plan_activity'").fetchone():
            return []
        rows = conn.execute(
            """
            SELECT detected_at, source_id, source_label, record_key, display_code, name, project, unit,
                   kind, old_value, new_value
            FROM plan_activity
            WHERE detected_at >= ?
            ORDER BY detected_at DESC, id DESC
            """,
            [cutoff],
        ).fetchall()
    items = []
    for row in rows:
        if selected not in ('全部', row['source_id']):
            continue
        if project != '全部' and text(row['project']) != project:
            continue
        if group != '全部' and text(row['unit']) != group:
            continue
        kind = row['kind']
        items.append({
            'detectedAt': row['detected_at'],
            'source': row['source_id'],
            'sourceLabel': row['source_label'],
            'code': row['record_key'],
            'displayCode': row['display_code'],
            'name': row['name'],
            'kind': kind,
            'kindLabel': KIND_LABELS.get(kind, kind),
            'oldValue': row['old_value'],
            'newValue': row['new_value'],
        })
    return items
