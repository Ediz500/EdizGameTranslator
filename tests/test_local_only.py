"""Local-only boundary and non-destructive legacy data migration."""
import ast
from copy import deepcopy
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from core import DEFAULTS,load_settings,save_settings
from region_profiles import with_region,region_for
from subtitle_store import SubtitleStore
from cloud_guard import NoCloudImports


class LocalOnlyTests(unittest.TestCase):
    def test_application_imports_with_cloud_sdk_forbidden(self):
        root=Path(__file__).resolve().parents[1]
        script="""import sys
sys.path[:0]=[sys.argv[1],sys.argv[1]+'/tests']
from cloud_guard import NoCloudImports
with NoCloudImports() as guard:
 import app,core,app_ui,overlay_server,translation_dispatch,package_checks
 assert not hasattr(core,'TranslationEngine')
 assert not hasattr(core,'BudgetLedger')
 assert not hasattr(core,'ContextMemory')
 assert not hasattr(app.MainWindow,'legacy_translate_worker')
 assert not hasattr(app.MainWindow,'legacy_test_ai')
 assert not guard.attempts
print('local-only imports OK')
"""
        r=subprocess.run([sys.executable,'-I','-c',script,str(root)],capture_output=True,text=True,timeout=20)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('local-only imports OK',r.stdout)

    def test_no_source_imports_the_removed_sdk_or_price_configuration(self):
        root=Path(__file__).resolve().parents[1]
        forbidden={'openai','httpx2','httpcore2','jiter','model_config'}
        for path in root.glob('*.py'):
            tree=ast.parse(path.read_text(encoding='utf8'))
            for node in ast.walk(tree):
                names=([a.name for a in node.names] if isinstance(node,ast.Import) else
                       [node.module or ''] if isinstance(node,ast.ImportFrom) else [])
                self.assertFalse(any(n.split('.')[0] in forbidden for n in names),path.name)
        self.assertFalse((root/'model_config.py').exists())

    def test_legacy_settings_keep_game_roi_notes_and_drop_cloud_fields_on_save(self):
        with tempfile.TemporaryDirectory() as folder,patch('core.config_folder',return_value=Path(folder)):
            settings=with_region(deepcopy(DEFAULTS),'Game',(.1,.3,.9,.95))
            settings.update(model='gpt-6-luna',budget_try=0,usd_try=0,estimated_total_usd=12.3,
                token_total_in=10,token_total_out=20,api_key_runtime='dummy',lore='Existing note')
            path=Path(folder)/'settings.json';path.write_text(json.dumps(settings),encoding='utf8')
            ledger=Path(folder)/'ledger.json';ledger.write_bytes(b'{"historical":"untouched"}')
            before=ledger.read_bytes();loaded=load_settings()
            self.assertEqual(loaded['game'],'Game')
            self.assertEqual(loaded['lore'],'Existing note')
            self.assertEqual(region_for(loaded,'Game'),(.1,.3,.9,.95))
            save_settings(loaded);saved=json.loads(path.read_text(encoding='utf8'))
            for key in ('model','budget_try','usd_try','estimated_total_usd','token_total_in','token_total_out','api_key_runtime'):
                self.assertNotIn(key,loaded);self.assertNotIn(key,saved)
            self.assertEqual(ledger.read_bytes(),before)

    def test_obs_vault_helpers_cannot_read_write_or_delete_a_legacy_api_key(self):
        import app
        with patch('keyring.get_password') as read,patch('keyring.set_password') as write,patch('keyring.delete_password') as delete:
            with self.assertRaises(ValueError):app.secret_get('openai_api_key')
            with self.assertRaises(ValueError):app.secret_save('openai_api_key','')
            read.assert_not_called();write.assert_not_called();delete.assert_not_called()
            read.return_value='dummy'
            self.assertEqual(app.secret_get('obs_password'),'dummy')
            read.assert_called_once_with(app.SERVICE,'obs_password')

    def test_old_sqlite_billing_and_translation_values_survive_without_new_tracking(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'history.sqlite3';store=SubtitleStore(path)
            store.db.execute('ALTER TABLE translation_jobs RENAME COLUMN translation_start_mono TO api_start_mono')
            for name,kind in [('input_tokens','INTEGER DEFAULT 0'),('output_tokens','INTEGER DEFAULT 0'),('estimated_usd','REAL DEFAULT 0'),('api_called','INTEGER DEFAULT 1'),('cost_unknown','INTEGER DEFAULT 0')]:
                store.db.execute(f'ALTER TABLE translation_jobs ADD COLUMN {name} {kind}')
            row=store.accept('old','Original source',1,1,1,1,.99,'fixture')
            job=store.enqueue_translation('old',row,'Original source','historical-model',1)
            store.db.execute("UPDATE translation_jobs SET translation_state='completed',display_state='completed',translated='Original translation',api_start_mono=2,ready_mono=3,input_tokens=100,output_tokens=20,estimated_usd=.25,api_called=1,cost_unknown=0 WHERE id=?",(job,))
            store.db.commit();store.close()
            with closing(sqlite3.connect(path)) as db:
                before=db.execute('SELECT source,translated,api_start_mono,input_tokens,output_tokens,estimated_usd,api_called,cost_unknown FROM translation_jobs').fetchone()
            with NoCloudImports():
                store=SubtitleStore(path)
                after=store.db.execute('SELECT source,translated,api_start_mono,input_tokens,output_tokens,estimated_usd,api_called,cost_unknown FROM translation_jobs WHERE id=?',(job,)).fetchone()
                self.assertEqual(before,after)
                self.assertEqual(store.db.execute('SELECT translation_start_mono FROM translation_jobs WHERE id=?',(job,)).fetchone()[0],2)
                new_row=store.accept('new','New source',4,4,4,4,.99,'fixture')
                new=store.enqueue_translation('new',new_row,'New source','local:ct2-marian',4)
                inherited=store.db.execute('SELECT input_tokens,output_tokens,estimated_usd,api_called,cost_unknown FROM translation_jobs WHERE id=?',(new,)).fetchone()
                store.claim_translation('new',5);store.complete_translation(new,'New translation',6)
                store.fail_translation(new,7)
                self.assertEqual(store.db.execute('SELECT input_tokens,output_tokens,estimated_usd,api_called,cost_unknown FROM translation_jobs WHERE id=?',(new,)).fetchone(),inherited)
                self.assertEqual(store.db.execute('SELECT source,translated,api_start_mono,input_tokens,output_tokens,estimated_usd,api_called,cost_unknown FROM translation_jobs WHERE id=?',(job,)).fetchone(),before)
                store.close()

    def test_historical_audit_separates_local_jobs_from_old_called_default(self):
        from local_benchmark import audit
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'audit.sqlite3';store=SubtitleStore(path)
            store.db.execute('ALTER TABLE translation_jobs ADD COLUMN api_called INTEGER DEFAULT 1')
            store.db.execute('ALTER TABLE translation_jobs ADD COLUMN api_start_mono REAL')
            row=store.accept('local','Scout: Go!',1,1,1,1,.99,'fixture')
            job=store.enqueue_translation('local',row,'Scout: Go!','local:ct2-marian',1)
            store.claim_translation('local',2);store.complete_translation(job,'Git!',3)
            old=store.accept('old','Scout: Stay here.',10,10,10,10,.99,'fixture')
            historical=store.enqueue_translation('old',old,'Scout: Stay here.','gpt-6-luna',10)
            store.db.execute("UPDATE translation_jobs SET translation_state='completed',display_state='completed',api_start_mono=11,translation_start_mono=NULL,ready_mono=12 WHERE id=?",(historical,))
            store.db.commit();store.close()
            before=hashlib.sha256(path.read_bytes()).hexdigest()
            with NoCloudImports():result=audit(path)
            self.assertEqual(result['stages_ms']['queue_ms']['n'],2)
            self.assertEqual(result['stages_ms']['api_ms']['n'],1)
            self.assertEqual(result['first_api_ms']['n'],1)
            self.assertEqual(result['sessions'][0]['session'],'old')
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)

    def test_new_sqlite_tracks_local_latency_without_financial_columns(self):
        store=SubtitleStore(':memory:')
        try:
            columns={r[1] for r in store.db.execute('PRAGMA table_info(translation_jobs)')}
            self.assertTrue({'input_tokens','output_tokens','estimated_usd','api_called','cost_unknown','api_start_mono'}.isdisjoint(columns))
            row=store.accept('s','Go!',0,0,0,.1,.99,'fixture')
            job=store.enqueue_translation('s',row,'Go!','local:ct2-marian',.1)
            store.claim_translation('s',.2);store.complete_translation(job,'Git!',.3)
            store.record_timing(job,dict(processing_ms=49,roundtrip_ms=50,capacity_wait_ms=1))
            stats=store.session_metrics('s')
            self.assertEqual(stats['stages_ms']['processing_ms']['p50'],49)
            self.assertAlmostEqual(stats['stages_ms']['translation_total_ms']['p50'],100)
            self.assertNotIn('api_ms',stats['stages_ms'])
            self.assertNotIn('estimated_usd',stats['models'][0])
        finally:store.close()

    def test_corpus_export_accepts_local_schema_without_modifying_database(self):
        from local_benchmark import export_corpus
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'corpus.sqlite3';store=SubtitleStore(path)
            for i in range(55):
                store.accept('s',f'Scout: Take {i} crates to the old station.',i,i,i,i,.99,'fixture',speaker='Scout')
            store.close();before=hashlib.sha256(path.read_bytes()).hexdigest()
            with NoCloudImports():corpus=export_corpus(path,50)
            self.assertEqual(corpus['selected'],50)
            self.assertFalse(any(e['luna_references'] for e in corpus['entries']))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
