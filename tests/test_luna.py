"""Model routing/accounting, migration, HTTP acknowledgements and lifecycle."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock,patch

from core import BudgetLedger,ContextMemory,TranslationEngine,DEFAULTS,load_settings,save_settings
from model_config import MODELS
from subtitle_store import SubtitleStore
from overlay_server import SharedOverlayState,launch_server


class ModelTests(unittest.TestCase):
    def test_completed_translation_not_silently_cut_at_500_characters(self):
        sdk=MagicMock();text='Tam anlamı korunan çeviri. '*25
        sdk.OpenAI.return_value.responses.create.return_value=SimpleNamespace(status='completed',output_text=text,usage=SimpleNamespace(input_tokens=100,output_tokens=200))
        with patch('openai.OpenAI',sdk.OpenAI):
            engine=TranslationEngine('offline','gpt-6-luna',ContextMemory('Test',''),BudgetLedger(0,1,10))
            translated,_=engine.translate('A long line.')
        self.assertEqual(translated,text.strip())

    def test_each_model_real_sdk_contract_and_own_standard_price(self):
        import httpx2,openai
        original=openai.OpenAI
        for model,effort,cost in [('gpt-6-luna','none',.000015),('gpt-6.1-terra','none',.00015),('gpt-6.1-sol','low',.0003)]:
            requests=[]
            def reply(request):
                requests.append(json.loads(request.content))
                return httpx2.Response(200,json=dict(id='resp_offline',object='response',created_at=0,status='completed',model=model,
                    output=[dict(type='message',id='msg_test',role='assistant',status='completed',content=[dict(type='output_text',text='Buradayım.',annotations=[])])],
                    usage=dict(input_tokens=100,output_tokens=10,total_tokens=110)))
            client=httpx2.Client(transport=httpx2.MockTransport(reply));ledger=BudgetLedger(0,1,10)
            with patch('openai.OpenAI',side_effect=lambda **kw:original(**kw,http_client=client)):
                engine=TranslationEngine('offline',model,ContextMemory('Test',''),ledger)
                try:text,usage=engine.translate('Here I am.')
                finally:engine.client.close()
            self.assertEqual(requests[0]['model'],model);self.assertEqual(requests[0]['reasoning']['effort'],effort)
            self.assertEqual(requests[0]['service_tier'],'default');self.assertFalse(requests[0]['store'])
            self.assertAlmostEqual(usage.usd,cost)

    def test_cache_reads_and_writes_use_selected_models_own_rates(self):
        for model,spec in MODELS.items():
            ledger=BudgetLedger(0,1,10);token=ledger.reserve(.05)
            usage=ledger.settle(token,model,100,10,cached_tokens=20,cache_write_tokens=30)
            self.assertAlmostEqual(usage.usd,(50*spec.input+20*spec.cached+30*spec.write+10*spec.output)/1e6)

    def test_unknown_model_fails_before_sdk(self):
        with patch('openai.OpenAI') as sdk:
            with self.assertRaises(ValueError):TranslationEngine('dummy','future-model',ContextMemory('',''),BudgetLedger(0,1,10))
        sdk.assert_not_called()

    def test_luna_default_persists_choice_without_resetting_existing_user(self):
        with tempfile.TemporaryDirectory() as folder,patch('core.config_folder',return_value=Path(folder)):
            self.assertEqual(load_settings()['model'],'gpt-6-luna')
            old=deepcopy(DEFAULTS);old.update(model='gpt-6.1-sol',estimated_total_usd=1.23,budget_try=321)
            save_settings(old);self.assertEqual(load_settings()['model'],'gpt-6.1-sol')
            old['model']='gpt-6-luna';save_settings(old)
            self.assertEqual(load_settings()['model'],'gpt-6-luna')
            self.assertEqual(load_settings()['estimated_total_usd'],1.23)


class StoreAndProtocolTests(unittest.TestCase):
    def test_charged_incomplete_result_remains_in_model_cost_totals(self):
        from core import TranslationUsage
        store=SubtitleStore(':memory:');row=store.accept('s','Source',1,1,1,1,.99,'test')
        job=store.enqueue_translation('s',row,'Source','gpt-6-luna',1)
        store.fail_translation(job,2,TranslationUsage(100,250,.000135))
        self.assertAlmostEqual(store.session_metrics('s')['models'][0]['estimated_usd'],.000135)
        self.assertEqual(store.db.execute('SELECT display_state FROM translation_jobs').fetchone()[0],'skipped')
        store.close()
    def test_local_memory_cache_does_not_falsify_api_latency_metrics(self):
        from core import TranslationUsage
        store=SubtitleStore(':memory:')
        row=store.accept('s','Source',1,1,1,1,.99,'test')
        job=store.enqueue_translation('s',row,'Source','gpt-6-luna',1)
        store.claim_translation('s',2)
        store.complete_translation(job,'Yerel önbellek',2.001,TranslationUsage(api_called=False))
        metrics=store.session_metrics('s')
        self.assertEqual(metrics['stages_ms']['ocr_accept_ms'],dict(p50=0,p95=0))
        self.assertEqual(metrics['stages_ms']['api_ms'],{})
        self.assertEqual(metrics['models'][0]['api_sample_count'],0)
        store.close()
    def test_migration_leaves_legacy_rows_and_restart_cancels_old_scene_queue(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'private.sqlite3';store=SubtitleStore(p)
            row=store.accept('old','Original',1,1,1,1,.99,'legacy')
            store.status(row,'translated_hidden','Old translation')
            store.db.commit();store.close()
            store=SubtitleStore(p)
            self.assertEqual(store.db.execute('SELECT text,status,translated FROM subtitles').fetchone(),('Original','translated_hidden','Old translation'))
            job=store.enqueue_translation('new',row,'Source','gpt-6-luna',2);store.complete_translation(job,'New',3)
            store.db.close()  # Simulated crash without a clean close.
            reopened=SubtitleStore(p)
            self.assertEqual(reopened.db.execute('SELECT display_state,cancel_reason FROM translation_jobs').fetchone(),('cancelled','process_restart'))
            reopened.close()

    def test_http_ack_generation_guard_and_no_pre_ack_countdown(self):
        from urllib.request import urlopen,Request
        from urllib.error import HTTPError
        state=SharedOverlayState();state.set('Gidelim.',10);server=launch_server(state,0)
        url=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(url+'/state') as r:first=json.load(r)
            self.assertIsNone(first['blocks'][0]['started'])
            payload=dict(generation=first['generation'],ids=[first['blocks'][0]['id']])
            with urlopen(Request(url+'/ack',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})) as r:self.assertEqual(r.status,204)
            self.assertIsNotNone(state.snapshot()['blocks'][0]['started'])
            state.clear();self.assertEqual(state.ack(payload['ids'],payload['generation']),0)
            with self.assertRaises(HTTPError):urlopen(Request(url+'/ack',data=b'{}',headers={'Content-Type':'text/plain'}))
            with self.assertRaises(HTTPError):urlopen(Request(url+'/ack',data=b'{}',headers={'Content-Type':'application/json','Origin':'https://example.invalid'}))
        finally:server.shutdown();server.server_close();state.close()

    def test_stop_while_browser_has_old_snapshot_cannot_restore_blocks(self):
        state=SharedOverlayState();state.set('Eski',10);old=state.snapshot()
        state.clear('source_lost');state.set('Yeni',10)
        self.assertEqual(state.ack([b['id'] for b in old['blocks']],old['generation']),0)
        self.assertEqual(state.current(),'Yeni');state.close()

    def test_actual_recorded_spiderman_replay_does_not_hide_existing_translations(self):
        from replay_display import compare
        data=json.loads(Path(__file__).with_name('spiderman_display_timing.json').read_text())
        result=compare(data)
        self.assertEqual((result['accepted'],result['existing_translations'],result['old_delivery_marked'],result['new_simulated_visible']),(57,49,19,49))
