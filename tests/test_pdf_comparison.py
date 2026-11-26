import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import Workbook

from cgn_import import import_excel
from dashboard_api import pdf_catalog
from dashboard_api.main import app
from test_dashboard_feedback import create_snapshot
from test_pdf_catalog import make_pdf


class PdfComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ae, self.cgn, self.catalog = root / 'ae.db', root / 'cgn.db', root / 'catalog.db'
        create_snapshot(self.ae)
        with sqlite3.connect(self.ae) as conn:
            conn.execute('DELETE FROM documents')
            columns = [r[1] for r in conn.execute('PRAGMA table_info(documents)')]
            for code in ('A', 'B', 'C', 'D', 'O', ''):
                values = {name: '' for name in columns}
                values.update({'文件编号': code, '文件名称': f'AE-{code}', '文件版本': 'V1', '流程状态': '完成', 'fetched_at': '2026-11-25'})
                conn.execute('INSERT INTO documents (' + ','.join('"'+c+'"' for c in columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')', [values[c] for c in columns])
        book = Workbook(); sheet = book.active
        sheet.append(['质量计划名称', '质量计划编码', '版本', '状态'])
        sheet.append(['广核A', 'A', 'V2', '审查中'])
        sheet.append(['广核A新版', 'A', 'V3', '审批中'])
        sheet.append(['广核B', 'B', 'V2', '审查中'])
        sheet.append(['广核B新版', 'B', 'V3', '审批中'])
        source = root / 'cgn.xlsx'; book.save(source); book.close()
        import_excel(self.cgn, source)
        self.env = patch.dict(os.environ, {'ECS_DB_PATH': str(self.ae), 'CGN_DB_PATH': str(self.cgn), 'PLAN_CATALOG_PATH': str(self.catalog)})
        self.env.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close(); self.env.stop(); self.tmp.cleanup()

    def save_pdf(self, codes):
        data = pdf_catalog.extract(make_pdf(first=5, second=len(codes)-5))
        for row, code in zip(data['rows'], codes):
            row['values'][2] = code
            row['values'][5] = 'A' if code == 'X-A' else 'V1'
        pdf_catalog.save(data, '虚构清单.pdf')

    def test_group_relations_and_missing_codes(self):
        self.assertFalse(self.client.get('/api/catalog/pdf/comparison').json()['hasPdf'])
        self.save_pdf(['A', 'A', 'B', 'C', 'C', 'D', 'M', '', 'X-A'])
        result = self.client.get('/api/catalog/pdf/comparison', params={'source': 'ae'}).json()
        self.assertTrue(result['hasPdf'])
        self.assertEqual(9, result['total'])  # Six numbered PDF groups, owner-only O, two separate missing-code groups.
        groups = {g['matchCode']: g for g in result['groups'] if g['matchCode']}
        self.assertEqual((3, 2, '多对多'), (groups['A']['ownerCount'], groups['A']['mineCount'], groups['A']['relation']))
        self.assertEqual({'ae', 'cgn'}, {r['source'] for r in groups['A']['owners']})
        self.assertTrue(next(r for r in groups['A']['owners'] if r['source'] == 'cgn')['recordKey'].startswith('cgn:'))
        self.assertEqual('A', next(r for r in groups['A']['owners'] if r['source'] == 'cgn')['originalCode'])
        self.assertEqual((3, 1, '一对多'), (groups['B']['ownerCount'], groups['B']['mineCount'], groups['B']['relation']))
        self.assertEqual((1, 2, '多对一'), (groups['C']['ownerCount'], groups['C']['mineCount'], groups['C']['relation']))
        self.assertEqual('一对一', groups['D']['relation'])
        self.assertEqual('仅我方有', groups['M']['category'])
        self.assertEqual('仅业主有', groups['O']['category'])
        self.assertEqual('待核对', groups['X-A']['category'])
        self.assertEqual(2, sum(not g['matchCode'] for g in result['groups']))
        self.assertEqual(2, len([g for g in result['groups'] if g['category'] == '待核对' and not g['matchCode']]))
        self.assertEqual(3, groups['M']['mine'][0]['page'])
        self.assertEqual('B', self.client.get('/api/catalog/pdf/comparison', params={'q': 'B'}).json()['groups'][0]['matchCode'])
        self.assertEqual(1, self.client.get('/api/catalog/pdf/comparison', params={'view': '仅业主有'}).json()['total'])
        self.assertEqual(3, self.client.get('/api/catalog/pdf/comparison', params={'view': '待核对'}).json()['total'])
        self.assertEqual(0, self.client.get('/api/catalog/pdf/comparison', params={'view': '双方都有', 'q': 'O'}).json()['total'])
        sections = self.client.get('/api/catalog/pdf/comparison/sections').json()['sections']
        self.assertEqual(['B'], [g['matchCode'] for g in sections['oneToMany']['groups']])
        self.assertEqual({'A', 'C', 'D'}, {g['matchCode'] for g in sections['otherMatched']['groups']})
        self.assertEqual(['M'], [g['matchCode'] for g in sections['mineOnly']['groups']])
        self.assertEqual(['O'], [g['matchCode'] for g in sections['ownerOnly']['groups']])
        self.assertEqual(3, sections['review']['total'])
        self.assertEqual((1, 3), (sections['oneToMany']['groups'][0]['mineCount'], sections['oneToMany']['groups'][0]['ownerCount']))

    def test_all_pdf_rows_beyond_first_page_and_fifty(self):
        data = pdf_catalog.extract(make_pdf())
        pdf_catalog.save(data, '长清单.pdf')
        for endpoint in ('/api/health', '/api/filters', '/api/overview', '/api/documents', '/api/catalog', '/api/catalog/pdf/latest'):
            response = self.client.get(endpoint)
            self.assertEqual(200, response.status_code, endpoint + ': ' + response.text[:100])
        result = self.client.get('/api/catalog/pdf/comparison', params={'page': 3}).json()
        self.assertEqual(61, result['total'])  # 55 PDF codes plus five AE and one blank AE code.
        self.assertIn('00A-055', [g['matchCode'] for g in result['groups']])


if __name__ == '__main__':
    unittest.main()
