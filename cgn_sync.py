from __future__ import annotations
import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path
from cgn_import import import_excel
from lan_sync_client import push_database
ROOT = Path(__file__).resolve().parent

def sync_once(excel=None, db=None, node='node', keep_excel=True):
    downloaded = excel is None
    expected_count = None
    if downloaded:
        with tempfile.TemporaryDirectory(prefix='cgn_result_') as temp:
            result_path = Path(temp)/'result.json'
            env = dict(os.environ)
            subprocess.run([node,str(ROOT/'collectors/cgn/run_sync.js'),str(result_path)],cwd=ROOT,env=env,check=True)
            # Node writes UTF-8 JSON; Windows' locale encoding can otherwise
            # mojibake non-ASCII download paths such as Chinese filenames.
            result = json.loads(result_path.read_text(encoding='utf-8'))
            if result.get('empty'): raise RuntimeError('广核查询无结果，保留已有数据，请核对查询范围')
            excel = Path(result['file']); expected_count = result['total']
    excel = Path(excel); db = Path(db or ROOT/'data/cgn_documents.db')
    stats = import_excel(db, excel, expected_count)
    print(f'[广核] 已保存 {stats["total"]} 份计划，新增 {stats["inserted"]}，更新 {stats["updated"]}',flush=True)
    try: push_database(db, source='cgn')
    except Exception as exc: print(f'[广核] 推送失败，本地数据已保留，下一轮重试：{exc}',flush=True)
    if downloaded and not keep_excel: excel.unlink(missing_ok=True)
    return stats

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description='广核纯 HTTP 下载、入库及内网同步')
    parser.add_argument('--excel',type=Path,help='只导入指定已下载表格，不登录平台')
    parser.add_argument('--db',type=Path); parser.add_argument('--node',default='node')
    args=parser.parse_args()
    try: sync_once(args.excel,args.db,args.node)
    except Exception as exc: print(f'[广核] 同步失败：{exc}',flush=True); raise SystemExit(1)
