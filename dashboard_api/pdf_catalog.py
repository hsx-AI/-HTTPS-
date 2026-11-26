"""Extract and retain PDF plan lists without changing the comparison baseline."""
from __future__ import annotations

import io
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from .catalog import MAX_ROWS, catalog_path

HEADERS = [
    '序号', '质量计划名称', '文件编号', '厂内编号', '质保分级', '版本号',
    '发布日期', '实际提交日期', '审批/实施状态', '批准函号', '负责单位',
]
TABLE_SETTINGS = (
    {'vertical_strategy': 'lines', 'horizontal_strategy': 'lines'},
    {'vertical_strategy': 'text', 'horizontal_strategy': 'text'},
)


def normalized(value: str | None) -> str:
    return ''.join((value or '').split())


def is_header(row: list) -> bool:
    return len(row) == len(HEADERS) and all(normalized(cell) == header for cell, header in zip(row, HEADERS))


def extract(payload: bytes) -> dict:
    if not payload.startswith(b'%PDF-'):
        raise ValueError('请上传有效的 PDF 文件')
    import pdfplumber

    rows, pages = [], []
    has_text = False
    try:
        with pdfplumber.open(io.BytesIO(payload)) as pdf:
            for page_number, page in enumerate(pdf.pages, 1):
                page_text = page.extract_text() or ''
                has_text |= bool(page_text.strip())
                matched = False
                for settings in TABLE_SETTINGS:
                    for table in page.find_tables(table_settings=settings):
                        extracted = table.extract()
                        header_positions = [i for i, row in enumerate(extracted) if is_header(row)]
                        if not header_positions:
                            continue
                        # The line and text strategies can find the same table. Use its first reliable match.
                        if matched:
                            raise ValueError(f'第 {page_number} 页发现多张指定表头的表格，请人工核对')
                        matched = True
                        start = header_positions[0] + 1
                        for row_number, row in enumerate(extracted[start:], start + 1):
                            if is_header(row):
                                continue
                            if len(row) != len(HEADERS) or any(cell is None for cell in row):
                                raise ValueError(f'第 {page_number} 页表格第 {row_number} 行无法可靠归入 11 列，请检查 PDF')
                            values = [cell.strip() for cell in row]
                            if not any(values):
                                continue
                            if len(rows) >= MAX_ROWS:
                                raise ValueError('清单最多支持 10000 条记录')
                            rows.append({'page': page_number, 'tableRow': row_number, 'values': values})
                    if matched:
                        break
                if matched:
                    pages.append(page_number)
                elif ''.join(HEADERS) in normalized(page_text):
                    raise ValueError(f'第 {page_number} 页有指定表头，但无法可靠识别 11 列表格，请检查 PDF')
            total_pages = len(pdf.pages)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('PDF 读取失败，请检查文件是否损坏或加密') from exc
    if not pages:
        if not has_text:
            raise ValueError('PDF 没有可提取的文本层，扫描件需要 OCR；本轮暂不支持')
        raise ValueError('未找到指定的质量计划清单表格')
    if not rows:
        raise ValueError('找到指定表头，但表格没有数据行')
    return {'headers': HEADERS, 'rows': rows, 'matchedPages': pages, 'matchedPageCount': len(pages), 'totalPages': total_pages, 'rowCount': len(rows)}


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute('''CREATE TABLE IF NOT EXISTS pdf_catalog_batches (
        id INTEGER PRIMARY KEY, filename TEXT NOT NULL, imported_at TEXT NOT NULL,
        matched_pages TEXT NOT NULL, total_pages INTEGER NOT NULL, row_count INTEGER NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pdf_catalog_rows (
        batch_id INTEGER NOT NULL, row_index INTEGER NOT NULL, page_number INTEGER NOT NULL,
        table_row INTEGER NOT NULL, values_json TEXT NOT NULL,
        PRIMARY KEY (batch_id, row_index),
        FOREIGN KEY (batch_id) REFERENCES pdf_catalog_batches(id))''')


def save(extracted: dict, filename: str) -> dict:
    rows = extracted['rows']
    if not rows or len(rows) != extracted['rowCount']:
        raise ValueError('PDF 清单数据不完整')
    path = catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    imported_at = datetime.now().astimezone().isoformat(timespec='seconds')
    with closing(sqlite3.connect(path)) as conn, conn:
        ensure_schema(conn)
        cursor = conn.execute(
            'INSERT INTO pdf_catalog_batches (filename, imported_at, matched_pages, total_pages, row_count) VALUES (?, ?, ?, ?, ?)',
            (Path(filename).name[:255], imported_at, json.dumps(extracted['matchedPages']), extracted['totalPages'], len(rows)),
        )
        batch_id = cursor.lastrowid
        conn.executemany(
            'INSERT INTO pdf_catalog_rows (batch_id, row_index, page_number, table_row, values_json) VALUES (?, ?, ?, ?, ?)',
            [(batch_id, i, row['page'], row['tableRow'], json.dumps(row['values'], ensure_ascii=False)) for i, row in enumerate(rows, 1)],
        )
    return {'batchId': batch_id, 'importedAt': imported_at, 'rowCount': len(rows), 'matchedPages': extracted['matchedPages']}


def latest(page: int = 1, page_size: int = 50) -> dict:
    empty = {'headers': HEADERS, 'batch': None, 'rows': [], 'total': 0, 'page': page, 'pageSize': page_size}
    path = catalog_path()
    if not path.exists():
        return empty
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='pdf_catalog_batches'").fetchone():
            return empty
        batch = conn.execute('SELECT * FROM pdf_catalog_batches ORDER BY id DESC LIMIT 1').fetchone()
        if batch is None:
            return empty
        rows = conn.execute(
            'SELECT row_index, page_number, table_row, values_json FROM pdf_catalog_rows WHERE batch_id=? ORDER BY row_index LIMIT ? OFFSET ?',
            (batch['id'], page_size, (page - 1) * page_size),
        ).fetchall()
        return {
            'headers': HEADERS,
            'batch': {'id': batch['id'], 'filename': batch['filename'], 'importedAt': batch['imported_at'],
                      'matchedPages': json.loads(batch['matched_pages']), 'totalPages': batch['total_pages']},
            'rows': [{'index': r['row_index'], 'page': r['page_number'], 'tableRow': r['table_row'],
                      'values': json.loads(r['values_json'])} for r in rows],
            'total': batch['row_count'], 'page': page, 'pageSize': page_size,
        }
