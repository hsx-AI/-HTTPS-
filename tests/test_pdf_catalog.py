import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import SimpleDocTemplate, PageBreak, Paragraph, Table, TableStyle

from dashboard_api import pdf_catalog
from dashboard_api.main import app


pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))


def make_pdf(first=28, second=27, target=True, text_layer=True):
    stream = io.BytesIO()
    document = SimpleDocTemplate(stream, pagesize=(950, 750), leftMargin=25, rightMargin=25, topMargin=25, bottomMargin=25)
    styles = getSampleStyleSheet()
    story = []
    if text_layer:
        story.append(Paragraph('封面', styles['Title']))
    story.append(PageBreak())
    story.append(Table([['无关表格', '文件编号'], ['忽略', 'X-1']], colWidths=[100, 100], style=TableStyle([('GRID', (0, 0), (-1, -1), .5, colors.black)])))
    if target:
        header = ['序\n号', '质量计划名称', '文件编号', '厂内编号', '质保分\n级', '版本号', '发布日期', '实际提交\n日期', '审批/实施\n状态', '批准函号', '负责单位']
        widths = [40, 110, 95, 90, 60, 55, 85, 85, 90, 90, 90]
        def plan_rows(start, count):
            return [[str(i), '计划\n甲' if i == 1 else f'计划{i}', f'00A-{i:03}', f'0B{i:03}', 'Q1', 'A01', '2026-11-01', '' if i == 1 else '2026-11-02', '待审批', '' if i == 1 else f'函{i}', '虚构单位'] for i in range(start, start + count)]
        style = TableStyle([('GRID', (0, 0), (-1, -1), .5, colors.black), ('FONTNAME', (0, 0), (-1, -1), 'STSong-Light'), ('FONTSIZE', (0, 0), (-1, -1), 7), ('VALIGN', (0, 0), (-1, -1), 'TOP')])
        story.append(Table([header, *plan_rows(1, first)], colWidths=widths, rowHeights=[30, 27, *([19] * (first - 1))], style=style))
        story.append(PageBreak())
        story.append(Table([header, *plan_rows(first + 1, second)], colWidths=widths, rowHeights=[30, *([19] * second)], style=style))
    document.build(story)
    return stream.getvalue()


class PdfCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'catalog.db'
        self.env = patch.dict(os.environ, {'PLAN_CATALOG_PATH': str(self.path), 'DASHBOARD_ADMIN_TOKEN': 'test-admin'})
        self.env.start()
        self.client = TestClient(app)
        self.auth = {'Authorization': 'Bearer test-admin'}

    def tearDown(self):
        self.client.close()
        self.env.stop()
        self.tmp.cleanup()

    def test_preview_import_and_latest_pagination(self):
        pdf = make_pdf()
        preview = self.client.post('/api/catalog/pdf/preview', content=pdf, headers=self.auth)
        self.assertEqual(200, preview.status_code, preview.text)
        data = preview.json()
        self.assertEqual([2, 3], data['matchedPages'])
        self.assertEqual(55, data['rowCount'])
        self.assertEqual(pdf_catalog.HEADERS, data['headers'])
        self.assertEqual(11, len(data['rows'][0]['values']))
        self.assertEqual('00A-001', data['rows'][0]['values'][2])
        self.assertEqual('', data['rows'][0]['values'][7])
        self.assertEqual('', data['rows'][0]['values'][9])
        self.assertIn('计划', data['rows'][0]['values'][1])
        self.assertEqual('6', data['rows'][5]['values'][0])
        self.assertEqual('00A-006', data['rows'][5]['values'][2])
        self.assertEqual('29', data['rows'][28]['values'][0])
        self.assertEqual(3, data['rows'][28]['page'])
        self.assertEqual('55', data['rows'][-1]['values'][0])
        self.assertEqual('00A-055', data['rows'][-1]['values'][2])
        self.assertFalse(self.path.exists())

        saved = self.client.post('/api/catalog/pdf/import?filename=虚构清单.pdf', content=pdf, headers=self.auth)
        self.assertEqual(200, saved.status_code, saved.text)
        self.assertEqual(55, saved.json()['rowCount'])
        self.client.close()
        self.client = TestClient(app)  # Simulates re-entering after a page refresh.
        first = self.client.get('/api/catalog/pdf/latest?page=1&pageSize=50').json()
        last = self.client.get('/api/catalog/pdf/latest?page=2&pageSize=50').json()
        self.assertEqual(55, first['total'])
        self.assertEqual(50, len(first['rows']))
        self.assertEqual(5, len(last['rows']))
        self.assertEqual('55', last['rows'][-1]['values'][0])
        self.assertEqual('00A-055', last['rows'][-1]['values'][2])
        self.assertEqual('虚构清单.pdf', first['batch']['filename'])

        # A failed import must leave the last committed batch visible.
        failed = self.client.post('/api/catalog/pdf/import?filename=错误.pdf', content=make_pdf(target=False), headers=self.auth)
        self.assertEqual(400, failed.status_code)
        self.assertIn('未找到指定的质量计划清单表格', failed.json()['detail'])
        self.assertEqual(55, self.client.get('/api/catalog/pdf/latest').json()['total'])

        # A database error halfway through row insertion rolls the new batch back.
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TRIGGER reject_pdf_row BEFORE INSERT ON pdf_catalog_rows WHEN NEW.row_index=2 BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            pdf_catalog.save(pdf_catalog.extract(pdf), '失败批次.pdf')
        self.assertEqual(55, self.client.get('/api/catalog/pdf/latest').json()['total'])

    def test_closing_preview_without_confirming_does_not_save(self):
        preview = self.client.post('/api/catalog/pdf/preview', content=make_pdf(), headers=self.auth)
        self.assertEqual(200, preview.status_code, preview.text)
        self.assertEqual(55, len(preview.json()['rows']))
        # Closing the browser preview sends no import request.
        self.assertFalse(self.path.exists())
        self.assertIsNone(self.client.get('/api/catalog/pdf/latest').json()['batch'])

    def test_no_text_layer_and_auth(self):
        self.assertEqual(401, self.client.post('/api/catalog/pdf/preview', content=make_pdf()).status_code)
        scanned = self.client.post('/api/catalog/pdf/preview', content=make_pdf(target=False, text_layer=False), headers=self.auth)
        # The unrelated table contains text; a truly image-only PDF is checked separately.
        self.assertIn('未找到指定的质量计划清单表格', scanned.json()['detail'])
        blank = io.BytesIO()
        SimpleDocTemplate(blank).build([PageBreak()])
        response = self.client.post('/api/catalog/pdf/preview', content=blank.getvalue(), headers=self.auth)
        self.assertEqual(400, response.status_code)
        self.assertIn('没有可提取的文本层', response.json()['detail'])


if __name__ == '__main__':
    unittest.main()
