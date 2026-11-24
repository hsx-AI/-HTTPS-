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
    ws.append(['质量计划名称', '质量计划编码', '版本', '状态', '审查结论', '审查意见', '创建日期', '项目', '机组', '供应商', '内部编码', '状态'])
    for row in rows:
        ws.append(row)
    book.save(path)
    book.close()


def cgn_row(name, code, version, status, conclusion='', opinion='', version_status='CFC'):
    return [name, code, version, status, conclusion, opinion, '2026-10-23', 'HYT', 'HYT5/6', '测试供方甲', 'IN-1', version_status]


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
            cgn_row('广核计划甲', 'CGN-A', 'A', '审查中'),
            cgn_row('广核计划乙', 'CGN-B', 'A', '已审查', opinion='通过'),
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

    def test_cgn_status_conclusion_and_new_version(self):
        next_file = self.root / 'cgn-next.xlsx'
        write_cgn_excel(next_file, [
            cgn_row('广核计划甲', 'CGN-A', 'A', '已审查', conclusion='ACC', opinion='意见已更新'),
            cgn_row('广核计划乙', 'CGN-B', 'A', '已审查', opinion='通过'),
            cgn_row('广核计划乙', 'CGN-B', 'B', '审查中'),
        ])
        next_cgn = self.root / 'cgn-next.db'
        import_excel(next_cgn, next_file)
        self.push(next_cgn, source='cgn')
        items = self.client.get('/api/activity', params={'source': 'cgn'}).json()['items']
        kinds = {item['kind'] for item in items}
        self.assertEqual({'added', 'status', 'conclusion'}, kinds)
        added = next(item for item in items if item['kind'] == 'added')
        self.assertIn('CGN-B', added['displayCode'])
        self.assertIn('B', added['displayCode'])
        status = next(item for item in items if item['kind'] == 'status')
        self.assertEqual('审查中', status['oldValue'])
        self.assertEqual('已审查', status['newValue'])
        self.assertEqual('已审查', status['newValue'])
        conclusion = next(item for item in items if item['kind'] == 'conclusion')
        self.assertEqual('', conclusion['oldValue'])
        self.assertEqual('ACC', conclusion['newValue'])
        self.assertEqual('审查结论变更', conclusion['kindLabel'])
        self.assertEqual(0, len(self.client.get('/api/activity', params={'source': 'ae'}).json()['items']))

    def test_cgn_comment_only_does_not_create_activity(self):
        next_file = self.root / 'cgn-comment.xlsx'
        write_cgn_excel(next_file, [
            cgn_row('广核计划甲', 'CGN-A', 'A', '审查中', opinion='仅审查意见变化'),
            cgn_row('广核计划乙', 'CGN-B', 'A', '已审查', opinion='通过'),
        ])
        next_cgn = self.root / 'cgn-comment.db'
        import_excel(next_cgn, next_file)
        self.push(next_cgn, source='cgn')
        self.assertEqual([], self.kinds('cgn'))

    def test_cgn_conclusion_code_change_keeps_previous_new_value(self):
        first = self.root / 'cgn-acc.xlsx'
        write_cgn_excel(first, [
            cgn_row('广核计划甲', 'CGN-A', 'A', '审查中', conclusion='ACC'),
            cgn_row('广核计划乙', 'CGN-B', 'A', '已审查'),
        ])
        first_db = self.root / 'cgn-acc.db'
        import_excel(first_db, first)
        self.push(first_db, source='cgn')
        second = self.root / 'cgn-rfc.xlsx'
        write_cgn_excel(second, [
            cgn_row('广核计划甲', 'CGN-A', 'A', '审查中', conclusion='RFC'),
            cgn_row('广核计划乙', 'CGN-B', 'A', '已审查'),
        ])
        second_db = self.root / 'cgn-rfc.db'
        import_excel(second_db, second)
        self.push(second_db, source='cgn')
        conclusions = [item for item in self.client.get('/api/activity', params={'source': 'cgn'}).json()['items'] if item['kind'] == 'conclusion']
        self.assertEqual(['RFC', 'ACC'], [item['newValue'] for item in conclusions])
        self.assertEqual(['ACC', ''], [item['oldValue'] for item in conclusions])

    def test_ae_version_status_is_ignored(self):
        next_ae = clone_db(self.ae, self.root / 'ae-version.db')
        update_ae(next_ae, 'HYT-005', 版本状态='NEWB')
        self.push(next_ae)
        self.assertEqual([], self.kinds('ae'))

    def test_consecutive_process_keeps_historical_new_value(self):
        first = clone_db(self.ae, self.root / 'ae-step1.db')
        update_ae(first, 'HYT-005', 流程状态='完成')
        self.push(first)
        second = clone_db(first, self.root / 'ae-step2.db')
        update_ae(second, 'HYT-005', 流程状态='供应商审核')
        self.push(second)
        process = [item for item in self.client.get('/api/activity').json()['items'] if item['kind'] == 'process' and item['displayCode'] == 'HYT-005']
        self.assertEqual(['供应商审核', '完成'], [item['newValue'] for item in process])
        self.assertEqual(['完成', '制造方编制'], [item['oldValue'] for item in process])

    def test_legacy_review_events_are_hidden_from_card(self):
        next_ae = clone_db(self.ae, self.root / 'ae-legacy.db')
        insert_ae(next_ae, 'HYT-LEGACY')
        self.push(next_ae)
        now = datetime.now().astimezone().isoformat(timespec='seconds')
        with closing(sqlite3.connect(self.activity_db)) as conn, conn:
            conn.execute(
                "INSERT INTO plan_activity (detected_at, source_id, source_label, record_key, display_code, name, project, unit, kind, old_value, new_value, sync_batch_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [now, 'cgn', '中广核 IMSQS 平台', 'cgn:legacy', 'LEGACY', '旧评论事件', 'HYT', 'HYT5/6', 'review', '旧评', '新评', 'legacy'],
            )
        kinds = [item['kind'] for item in self.client.get('/api/activity').json()['items']]
        self.assertIn('added', kinds)
        self.assertNotIn('review', kinds)

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
            cgn_row('广核计划甲', 'CGN-A', 'A', '审查中'),
        ])
        next_cgn = self.root / 'cgn-drop.db'
        import_excel(next_cgn, next_file)
        self.push(next_cgn, source='cgn')
        self.assertEqual([], self.kinds('cgn'))


if __name__ == '__main__':
    unittest.main()
