import csv
import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import Workbook
from dashboard_api import catalog, queries
from dashboard_api.main import app
from excel_db import EXCEL_COLUMNS


def create_snapshot(path):
    with closing(sqlite3.connect(path)) as conn, conn:
        columns = EXCEL_COLUMNS + ['fetched_at', 'source_file', 'updated_at']
        conn.execute('CREATE TABLE documents (' + ','.join(f'"{c}" TEXT' for c in columns) + ')')
        conn.execute('CREATE TABLE document_changes (id INTEGER PRIMARY KEY, "文件编号" TEXT, field_name TEXT, old_value TEXT, new_value TEXT, changed_at TEXT, source_file TEXT, sync_batch_id TEXT)')
        for i in range(42):
            row = {k: '' for k in columns}
            row.update({'文件名称': f'测试质量计划 {i:02}', '文件编号': f'HYT-{i:03}', '所属项目': 'HYT' if i < 40 else 'LCT', '适用机组号': 'HYT5/6' if i < 40 else 'LCT1', '制造单位': '测试供方甲' if i % 2 == 0 else '测试供方乙', '流程状态': '完成' if i < 4 else '上海院审查意见批准' if i == 4 else '制造方编制', '创建时间': '2026-10-15', '核安全报送级别': 'NNS' if i % 2 else '', '发起人': '测试人员', 'fetched_at': '2026-10-19 10:00:00', 'updated_at': '2026-10-19 10:00:00'})
            conn.execute('INSERT INTO documents VALUES ('+','.join('?' for _ in columns)+')', [row[c] for c in columns])
            conn.execute('INSERT INTO document_changes ("文件编号",field_name,old_value,new_value,changed_at,source_file,sync_batch_id) VALUES (?,?,?,?,?,?,?)', [row['文件编号'], '流程状态', '制造方审核', row['流程状态'], '2026-10-19 09:00:00', 'test.xls', 'test-batch'])


class DashboardFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'ecs_documents.db'
        create_snapshot(self.db)
        self.env = patch.dict(os.environ, {'ECS_DB_PATH': str(self.db), 'PLAN_CATALOG_PATH': str(Path(self.tmp.name) / 'catalog.db'), 'DASHBOARD_ADMIN_TOKEN': 'test-admin', 'LAN_SYNC_TOKEN': 'test-sync'})
        self.env.start()
        self.client = TestClient(app)
        self.auth = {'Authorization': 'Bearer test-admin'}
        self.mapping = {k: i for i, k in enumerate(catalog.FIELDS)}

    def tearDown(self):
        self.client.close(); self.env.stop(); self.tmp.cleanup()

    def import_plan(self, code='HYT-000', internal='0EA.657.0001', name='测试质量计划 00', approval='2026-10-18 08:30:00'):
        return catalog.import_rows([[name, code, internal, 'HYT', 'HYT5/6', '测试供方甲', '2026-11-01', approval]], self.mapping, '清单.csv')

    def test_overview_drilldowns_and_dynamic_filters(self):
        options = self.client.get('/api/filters').json()
        self.assertEqual(['全部', 'HYT5/6'], options['projectGroups']['HYT'])
        self.assertIn('上海院审查意见批准', options['statuses'])
        overview = self.client.get('/api/overview').json()
        for stat in overview['statusStats']:
            result = self.client.get('/api/documents', params={'status': stat['label']}).json()
            self.assertEqual(stat['value'], result['total'])
        self.assertEqual(38, self.client.get('/api/documents', params={'status': '处理中'}).json()['total'])
        for stat in overview['reportingStats']:
            result = self.client.get('/api/documents', params={'reportLevel': stat['label']}).json()
            self.assertEqual(stat['value'], result['total'])
        response = self.client.get('/api/export', params={'reportLevel': '未填写', 'company': '测试供方甲'})
        rows = list(csv.reader(io.StringIO(response.text.lstrip('\ufeff'))))
        self.assertEqual(22, len(rows))
        self.assertIn('最近审批时间', rows[0])

    def test_notes_survive_received_snapshot_and_are_searchable(self):
        response = self.client.put('/api/documents/note', headers=self.auth, json={'code': 'HYT-005', 'internalCode': '0EA.657.9001'})
        self.assertEqual(200, response.status_code)
        self.assertEqual([], catalog.read_catalog())
        result = self.client.get('/api/documents', params={'q': '0EA.657.9001'}).json()
        self.assertEqual(1, result['total'])
        self.assertEqual('用户备注', result['items'][0]['internalCodeSource'])
        self.assertIsNone(result['items'][0]['latestApprovalAt'])
        self.import_plan()
        content = self.db.read_bytes()
        received = self.client.put('/api/sync/database', content=content, headers={'Authorization': 'Bearer test-sync'})
        self.assertEqual(200, received.status_code, received.text)
        self.assertEqual('0EA.657.9001', self.client.get('/api/documents', params={'q': 'HYT-005'}).json()['items'][0]['internalCode'])
        self.assertEqual(1, len(catalog.read_catalog()))
        self.assertEqual(200, self.client.put('/api/documents/note', headers=self.auth, json={'code': 'HYT-005', 'internalCode': ''}).status_code)
        self.assertEqual(0, self.client.get('/api/documents', params={'q': '0EA.657.9001'}).json()['total'])

    def test_trace_search_pagination_and_selected_changes(self):
        first = self.client.get('/api/trace').json()
        self.assertEqual(38, first['total']); self.assertEqual([], first['recentChanges'])
        second = self.client.get('/api/trace', params={'page': 2}).json()
        self.assertEqual(15, len(second['inProgress']))
        code = second['inProgress'][0]['code']
        selected = self.client.get('/api/trace', params={'page': 2, 'code': code}).json()
        self.assertEqual([code], [c['code'] for c in selected['recentChanges']])
        excluded = self.client.get('/api/trace', params={'project': 'LCT', 'code': code}).json()
        self.assertEqual([], excluded['recentChanges'])
        found = self.client.get('/api/trace', params={'q': 'HYT-004', 'code': 'HYT-004'}).json()
        self.assertEqual(1, found['total']); self.assertEqual('上海院审查意见批准', found['inProgress'][0]['status'])

    def test_import_preview_xlsx_and_csv(self):
        book = Workbook(); book.active.title = '封面'; book.active.append(['说明'])
        sheet = book.create_sheet('清单'); sheet.append(['质量计划清单']); sheet.append([v[0] for v in catalog.FIELDS.values()])
        sheet.append(['测试计划', 'HYT-000', '0EA.657.1', 'HYT', 'HYT5/6', '测试供方甲', datetime(2026, 11, 1), datetime(2026, 10, 18, 8, 30)])
        stream = io.BytesIO(); book.save(stream); book.close()
        response = self.client.post('/api/catalog/preview', params={'filename': '清单.xlsx', 'sheet': '清单'}, content=stream.getvalue(), headers=self.auth)
        self.assertEqual(200, response.status_code, response.text)
        preview = response.json(); self.assertEqual(2, preview['headerRow']); self.assertEqual(1, len(preview['rows']))
        response = self.client.post('/api/catalog/import', json={**preview, 'filename': '清单.xlsx'}, headers=self.auth)
        self.assertEqual(200, response.status_code, response.text)
        actual = self.client.get('/api/documents', params={'q': 'HYT-000'}).json()['items'][0]
        self.assertEqual('2026-10-18 08:30:00', actual['latestApprovalAt'])
        self.assertEqual('导入清单', actual['latestApprovalSource'])
        comparison = self.client.get('/api/catalog').json()
        self.assertEqual({'已完成': 1}, comparison['summary']); self.assertEqual(100, comparison['completionRate'])
        self.assertEqual(41, comparison['extraCount'])
        preview = catalog.preview_file('计划名称,文件编号\n计划甲,A-001\n'.encode('gb18030'), '清单.csv')
        self.assertEqual('计划甲', preview['rows'][0][0])

    def test_import_rejects_duplicates_atomically_and_updates_existing(self):
        self.import_plan()
        result = self.import_plan(approval='2026-10-19 09:00:00')
        self.assertEqual(1, result['updated']); self.assertEqual(1, len(catalog.read_catalog()))
        row = ['计划乙', 'HYT-001', '', 'HYT', 'HYT5/6', '', '', '']
        with self.assertRaises(ValueError): catalog.import_rows([row, row], self.mapping, '重复.csv')
        self.assertEqual(1, len(catalog.read_catalog()))
        with self.assertRaises(ValueError): self.import_plan(code='HYT-002', approval='昨天')
        self.assertEqual(1, len(catalog.read_catalog()))

    def test_matching_ambiguity_and_missing_items_are_not_completed(self):
        self.import_plan()
        catalog.import_rows([['同项', '', '', 'HYT', 'HYT5/6', '', '', '']], self.mapping, '清单.csv')
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('UPDATE documents SET "文件名称"=? WHERE "文件编号" IN (?,?)', ['同项', 'HYT-001', 'HYT-002'])
        result = self.client.get('/api/catalog').json()
        self.assertEqual({'已完成': 1, '待核对': 1}, result['summary'])
        self.assertEqual(50, result['completionRate']); self.assertEqual(39, result['extraCount'])
        self.import_plan(code='MISSING', internal='', name='未接入计划', approval='')
        self.assertEqual(1, self.client.get('/api/catalog').json()['summary']['未接入'])
        # Identical names with an explicit unmatched code must not be silently joined.
        self.import_plan(code='DIFFERENT', internal='', name='测试质量计划 00', approval='')
        self.assertEqual(2, self.client.get('/api/catalog').json()['summary']['未接入'])

    def test_import_and_notes_require_maintenance_token(self):
        self.assertEqual(401, self.client.post('/api/catalog/preview?filename=a.csv', content=b'a,b').status_code)
        self.assertEqual(401, self.client.put('/api/documents/note', json={'code': 'HYT-000', 'internalCode': 'A'}).status_code)
        with patch.dict(os.environ, {'DASHBOARD_ADMIN_TOKEN': ''}):
            self.assertEqual(503, self.client.post('/api/catalog/import', headers=self.auth, json={}).status_code)

    def test_imported_internal_code_does_not_create_a_second_match(self):
        self.import_plan(approval='2026-10-18')
        catalog.import_rows([['另一计划', '', '0EA.657.0001', 'HYT', 'HYT5/6', '', '', '']], self.mapping, '清单.csv')
        result = self.client.get('/api/catalog').json()
        self.assertEqual({'已完成': 1, '未接入': 1}, result['summary'])
        self.assertEqual('2026-10-18', result['items'][0]['actual']['latestApprovalAt'])
        # An independently entered user note is real matching evidence, so the collision must be reviewed.
        catalog.save_note('HYT-000', '0EA.657.0001')
        self.assertEqual({'待核对': 2}, self.client.get('/api/catalog').json()['summary'])


if __name__ == '__main__':
    unittest.main()
