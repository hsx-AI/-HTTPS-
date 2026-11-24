import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import Workbook

from dashboard_api import activity
from dashboard_api.main import app
from cgn_import import import_excel
from test_dashboard_feedback import create_snapshot


def clone_db(src: Path, dest: Path) -> Path:
    dest.write_bytes(src.read_bytes())
    return dest


def update_ae(path: Path, code: str, **fields):
    assignments = ', '.join(f'"{k}"=?' for k in fields)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(f'UPDATE documents SET {assignments} WHERE "文件编号"=?', [*fields.values(), code])


def insert_ae(path: Path, code: str, name='新增测试计划', status='制造方编制'):
    with closing(sqlite3.connect(path)) as conn, conn:
        columns = [row[1] for row in conn.execute('PRAGMA table_info(documents)')]
        values = {k: '' for k in columns}
        values.update({'文件名称': name, '文件编号': code, '流程状态': status, '所属项目': 'HYT', '适用机组号': 'HYT5/6', 'fetched_at': '2026-11-24 10:00:00'})
        conn.execute('INSERT INTO documents (' + ','.join(f'"{c}"' for c in columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')', [values[c] for c in columns])


def write_cgn_excel(path: Path, rows: list[list]):
    book = Workbook()
    ws = book.active
    ws.append(['质量计划名称', '质量计划编码', '版本', '状态', '审查评论', '创建日期', '项目', '机组', '供应商', '内部编码', '状态'])
    for row in rows:
        ws.append(row)
    book.save(path)
    book.close()


class PlanActivityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ae = self.root / 'ecs_documents.db'
        self.cgn = self.root / 'cgn_documents.db'
        self.activity_db = self.root / 'quality_plan_activity.db'
        create_snapshot(self.ae)
        self.cgn_file = self.root / 'cgn.xlsx'
        write_cgn_excel(self.cgn_file, [
            ['广核计划甲', 'CGN-A', 'A', '审查中', '初审意见较短', '2026-10-23', 'HYT', 'HYT5/6', '测试供方甲', 'IN-1', 'CFC'],
            ['广核计划乙', 'CGN-B', 'A', '已审查', '通过', '2026-10-23', 'HYT', 'HYT5/6', '测试供方甲', 'IN-2', 'CFC'],
        ])
        import_excel(self.cgn, self.cgn_file)
        self.env = patch.dict(os.environ, {
            'ECS_DB_PATH': str(self.ae),
            'CGN_DB_PATH': str(self.cgn),
            'PLAN_ACTIVITY_PATH': str(self.activity_db),
            'LAN_SYNC_TOKEN': 'test-sync',
            'DASHBOARD_ADMIN_TOKEN': 'test-admin',
        })
        self.env.start()
        self.client = TestClient(app)
        self.auth = {'Authorization': 'Bearer test-sync'}

    def tearDown(self):
        self.client.close()
        self.env.stop()
        self.tmp.cleanup()

    def push(self, path: Path, source='ae'):
        query = '' if source == 'ae' else '?source=cgn'
        response = self.client.put('/api/sync/database' + query, headers=self.auth, content=path.read_bytes())
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def kinds(self, source='全部'):
        return [(item['kind'], item['displayCode'], item.get('oldValue'), item.get('newValue')) for item in self.client.get('/api/activity', params={'source': source}).json()['items']]

    def test_first_receive_is_baseline_only(self):
        empty_ae = self.root / 'empty-ae.db'
        create_snapshot(empty_ae)
        os.unlink(self.ae)
        self.push(empty_ae)
        self.assertEqual([], self.kinds())
        self.assertFalse(self.activity_db.exists())
        self.assertTrue(self.ae.exists())

    def test_added_and_ae_process_change(self):
        next_ae = clone_db(self.ae, self.root / 'ae-next.db')
        insert_ae(next_ae, 'HYT-NEW', '新接入计划')
        update_ae(next_ae, 'HYT-005', 流程状态='完成')
        update_ae(next_ae, 'HYT-006', source_file='ignored.xls', fetched_at='2099-01-01 00:00:00')
        self.push(next_ae)
        items = self.client.get('/api/activity').json()['items']
        self.assertEqual({'added', 'process'}, {item['kind'] for item in items})
        added = next(item for item in items if item['kind'] == 'added')
        self.assertEqual('新接入计划', added['name'])
        self.assertEqual('HYT-NEW', added['displayCode'])
        self.assertEqual('AE 协调平台', added['sourceLabel'])
        process = next(item for item in items if item['kind'] == 'process')
        self.assertEqual('制造方编制', process['oldValue'])
        self.assertEqual('完成', process['newValue'])
        self.assertEqual('流程变更', process['kindLabel'])
        self.assertTrue(any(item['kind'] == 'added' for item in self.client.get('/api/overview').json()['recentActivity']))

    def test_cgn_status_review_and_new_version(self):
        next_file = self.root / 'cgn-next.xlsx'
        write_cgn_excel(next_file, [
            ['广核计划甲', 'CGN-A', 'A', '已审查', '这是一条明显更长的审查评论，用于确认页面可以缩略后仍能查看完整内容。' * 2, '2026-10-23', 'HYT', 'HYT5/6', '测试供方甲', 'IN-1', 'CFC'],
            ['广核计划乙', 'CGN-B', 'A', '已审查', '通过', '2026-10-23', 'HYT', 'HYT5/6', '测试供方甲', 'IN-2', 'CFC'],
            ['广核计划乙', 'CGN-B', 'B', '审查中', '新版本评论', '2026-10-24', 'HYT', 'HYT5/6', '测试供方甲', 'IN-3', 'CFC'],
        ])
        next_cgn = self.root / 'cgn-next.db'
        import_excel(next_cgn, next_file)
        self.push(next_cgn, source='cgn')
        items = self.client.get('/api/activity', params={'source': 'cgn'}).json()['items']
        kinds = {item['kind'] for item in items}
        self.assertEqual({'added', 'status', 'review'}, kinds)
        added = next(item for item in items if item['kind'] == 'added')
        self.assertIn('CGN-B', added['displayCode'])
        self.assertIn('B', added['displayCode'])
        status = next(item for item in items if item['kind'] == 'status')
        self.assertEqual('审查中', status['oldValue'])
        self.assertEqual('已审查', status['newValue'])
        review = next(item for item in items if item['kind'] == 'review')
        self.assertIn('审查评论', review['kindLabel'])
        self.assertTrue(review['newValue'].startswith('这是一条明显更长'))
        self.assertEqual(0, len(self.client.get('/api/activity', params={'source': 'ae'}).json()['items']))

    def test_duplicate_push_does_not_repeat_activity(self):
        next_ae = clone_db(self.ae, self.root / 'ae-dup.db')
        insert_ae(next_ae, 'HYT-DUP')
        self.push(next_ae)
        self.assertEqual(1, len(self.kinds('ae')))
        self.push(next_ae)
        self.assertEqual(1, len(self.kinds('ae')))

    def test_old_events_leave_seven_day_window(self):
        next_ae = clone_db(self.ae, self.root / 'ae-window.db')
        insert_ae(next_ae, 'HYT-KEEP')
        self.push(next_ae)
        stale = (datetime.now().astimezone() - timedelta(days=8)).isoformat(timespec='seconds')
        with closing(sqlite3.connect(self.activity_db)) as conn, conn:
            conn.execute("UPDATE plan_activity SET detected_at=? WHERE record_key='HYT-KEEP'", [stale])
        self.assertEqual([], self.kinds())
        still_keep = clone_db(next_ae, self.root / 'ae-keep.db')
        insert_ae(still_keep, 'HYT-FRESH', '窗口内计划')
        self.push(still_keep)
        items = self.client.get('/api/activity').json()['items']
        self.assertEqual(['HYT-FRESH'], [item['displayCode'] for item in items])

    def test_activity_error_does_not_block_replace(self):
        next_ae = clone_db(self.ae, self.root / 'ae-error.db')
        insert_ae(next_ae, 'HYT-ERR')
        with patch.object(activity, 'diff_snapshots', side_effect=RuntimeError('对比失败')):
            result = self.push(next_ae)
        self.assertTrue(result['ok'])
        with closing(sqlite3.connect(self.ae)) as conn:
            self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM documents WHERE "文件编号"=?', ['HYT-ERR']).fetchone()[0])
        self.assertEqual([], self.kinds())

    def test_activity_save_error_after_replace_still_serves_new_db(self):
        next_ae = clone_db(self.ae, self.root / 'ae-save.db')
        insert_ae(next_ae, 'HYT-SAVE')
        with patch.object(activity, 'save_events', side_effect=RuntimeError('写入失败')):
            self.push(next_ae)
        with closing(sqlite3.connect(self.ae)) as conn:
            self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM documents WHERE "文件编号"=?', ['HYT-SAVE']).fetchone()[0])
        self.assertEqual([], self.kinds())

    def test_missing_cgn_plan_is_not_listed_as_deleted(self):
        next_file = self.root / 'cgn-drop.xlsx'
        write_cgn_excel(next_file, [
            ['广核计划甲', 'CGN-A', 'A', '审查中', '初审意见较短', '2026-10-23', 'HYT', 'HYT5/6', '测试供方甲', 'IN-1', 'CFC'],
        ])
        next_cgn = self.root / 'cgn-drop.db'
        import_excel(next_cgn, next_file)
        self.push(next_cgn, source='cgn')
        self.assertEqual([], self.kinds('cgn'))


if __name__ == '__main__':
    unittest.main()
