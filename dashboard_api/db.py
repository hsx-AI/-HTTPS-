from __future__ import annotations
import json
import os
import sqlite3
from contextvars import ContextVar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT/'data/ecs_documents.db'
SOURCES = {'ae':'AE 协调平台','cgn':'中广核 IMSQS 平台'}
active_source = ContextVar('dashboard_source', default='全部')
BASE_COLUMNS = ['文件名称','文件编号','文件版本','所属项目','制造单位','流程状态','版本状态','是否分章节','创建时间','发起人','文件类别','适用机组号','供应商名称','设备名称','合同号','核安全报送级别','是否采购分包','是否含SPV设备','SPV位号','总包方部门','板块','相关供方工作模式','制造单位供方级别','审查结论','发起单位','fetched_at','source_file','updated_at','内部编号','最新审批流程时间','display_code','raw_data','completion_state','source_id','source_label']
CHANGE_COLUMNS = ['id','文件编号','field_name','old_value','new_value','changed_at','source_file','sync_batch_id','source_id','source_label','display_code']

def resolve_db_path(source='ae') -> Path:
    if source not in SOURCES: raise ValueError('不支持的数据平台')
    default = DEFAULT_DB if source == 'ae' else resolve_db_path('ae').parent/'cgn_documents.db'
    raw = os.environ.get('ECS_DB_PATH' if source=='ae' else 'CGN_DB_PATH','').strip()
    path = Path(raw) if raw else default
    return path if path.is_absolute() else ROOT/path

def qident(name): return '"'+name.replace('"','""')+'"'

def available_sources():
    return [{'id':key,'label':label,'available':resolve_db_path(key).exists()} for key,label in SOURCES.items()]

def connect(db_path=None):
    """Read independent snapshots into a common query view; never alter source databases."""
    conn = sqlite3.connect(':memory:',check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE documents ('+','.join(qident(k)+' TEXT' for k in BASE_COLUMNS)+')')
    conn.execute('CREATE TABLE document_changes ('+','.join(qident(k)+(' INTEGER' if k=='id' else ' TEXT') for k in CHANGE_COLUMNS)+')')
    selected = active_source.get()
    try:
        for source,label in SOURCES.items():
            if selected not in ('全部',source): continue
            path = Path(db_path) if db_path is not None and source=='ae' else resolve_db_path(source)
            if not path.exists(): continue
            read = sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
            read.row_factory = sqlite3.Row
            try:
                rows=[]; display={}
                for raw in read.execute('SELECT * FROM documents'):
                    d=dict(raw); key=d['文件编号']; display[key]=d.get('display_code') or key
                    d['内部编号'] = d.get('内部编号') or d.get('内部文件编号','')
                    d['最新审批流程时间'] = d.get('最新审批流程时间') or d.get('最新审批时间','')
                    d['display_code']=display[key]; d['source_id']=source; d['source_label']=label
                    d['completion_state']=d.get('completion_state') or ('done' if d.get('流程状态')=='完成' else 'active')
                    if not d.get('raw_data'):
                        d['raw_data']=json.dumps([{'name':k,'label':k,'value':v or ''} for k,v in dict(raw).items() if k not in ('fetched_at','updated_at','source_file')],ensure_ascii=False)
                    rows.append([d.get(k,'') for k in BASE_COLUMNS])
                conn.executemany('INSERT INTO documents VALUES ('+','.join('?' for _ in BASE_COLUMNS)+')',rows)
                changes=[]
                for raw in read.execute('SELECT * FROM document_changes'):
                    d=dict(raw); d.update(source_id=source,source_label=label,display_code=display.get(d['文件编号'],d['文件编号']))
                    changes.append([d.get(k,'') for k in CHANGE_COLUMNS])
                conn.executemany('INSERT INTO document_changes VALUES ('+','.join('?' for _ in CHANGE_COLUMNS)+')',changes)
            finally: read.close()
        conn.commit()
        return conn
    except Exception:
        conn.close(); raise
