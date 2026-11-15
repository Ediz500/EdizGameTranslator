import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from local_translation import (LOCAL_MODELS,LocalWorkerClient,LocalWorkerError,
    check_model_path,gemma_messages,milmmt_prompt,experimental_gemma_prompt)
from local_benchmark import export_corpus,percentiles,quality_summary,QUALITY_FIELDS,review_sheet
from subtitle_store import SubtitleStore


class LocalBenchmarkTests(unittest.TestCase):
    def manifest(self,folder):
        (Path(folder)/'ediz_model.json').write_text(json.dumps(dict(model_id=LOCAL_MODELS['milmmt-1b'],revision='test-sha')),encoding='utf-8')

    def test_official_prompts_and_experimental_context_separate(self):
        self.assertEqual(milmmt_prompt('Wait.'),'Translate this from English to Turkish:\nEnglish: Wait.\nTurkish:')
        m=gemma_messages('Wait.')
        self.assertEqual(len(m),1);self.assertEqual(len(m[0]['content']),1)
        self.assertEqual(m[0]['content'][0],dict(type='text',source_lang_code='en',target_lang_code='tr',text='Wait.'))
        self.assertNotIn('context',str(m))
        self.assertIn('PREVIOUS:',experimental_gemma_prompt('Wait.','Stay here.'))

    def test_pretrain_and_mismatched_manifest_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as folder,patch('local_translation.subprocess.Popen') as popen:
            self.manifest(folder)
            with self.assertRaises(ValueError):check_model_path('MiLMMT-46-1B-Pretrain',folder)
            with self.assertRaises(ValueError):LocalWorkerClient(sys.executable,'translategemma-4b',folder)
            popen.assert_not_called()

    def test_warm_process_and_offline_environment(self):
        real_popen=subprocess.Popen;launches=[]
        script="import sys,json;print(json.dumps({'ready':True,'load_ms':1}),flush=True)\nfor line in sys.stdin: print(json.dumps({'text':'Bekle.','complete':True}),flush=True)"
        def launch(command,**kwargs):
            launches.append((command,kwargs))
            return real_popen([sys.executable,'-u','-c',script],**kwargs)
        with tempfile.TemporaryDirectory() as folder,patch('local_translation.subprocess.Popen',side_effect=launch):
            self.manifest(folder);client=LocalWorkerClient(sys.executable,'milmmt-1b',folder)
            try:
                self.assertEqual(client.translate('Wait.')['text'],'Bekle.')
                self.assertTrue(client.translate('Wait again.')['complete'])
                self.assertEqual(len(launches),1)
                self.assertEqual(launches[0][1]['env']['HF_HUB_OFFLINE'],'1')
                self.assertEqual(launches[0][1]['env']['TRANSFORMERS_OFFLINE'],'1')
                self.assertNotIn('api_key',str(launches[0][0]))
            finally:client.close()
            self.assertIsNotNone(client.process.poll())

    def test_load_timeout_terminates_child(self):
        real_popen=subprocess.Popen;children=[]
        def launch(command,**kwargs):
            child=real_popen([sys.executable,'-u','-c','import time;time.sleep(30)'],**kwargs)
            children.append(child);return child
        with tempfile.TemporaryDirectory() as folder,patch('local_translation.subprocess.Popen',side_effect=launch):
            self.manifest(folder)
            with self.assertRaises(LocalWorkerError):LocalWorkerClient(sys.executable,'milmmt-1b',folder,load_timeout=.1)
            self.assertIsNotNone(children[0].poll())

    def test_worker_crash_is_explicit_and_no_api_fallback(self):
        real_popen=subprocess.Popen
        script="import json;print(json.dumps({'error':'CUDA out of memory'}),flush=True)"
        def launch(command,**kwargs):return real_popen([sys.executable,'-u','-c',script],**kwargs)
        with tempfile.TemporaryDirectory() as folder,patch('local_translation.subprocess.Popen',side_effect=launch),patch('openai.OpenAI') as paid:
            self.manifest(folder)
            with self.assertRaisesRegex(LocalWorkerError,'CUDA out of memory'):LocalWorkerClient(sys.executable,'milmmt-1b',folder)
            paid.assert_not_called()

    def test_real_sqlite_export_is_readonly_unique_and_keeps_luna_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.sqlite3';s=SubtitleStore(path)
            for i in range(55):
                row=s.accept('s',f'Scout: Take {i} crates to the old station.',i,i,i,i,.99,'test',speaker='Scout')
                if i==0:
                    j=s.enqueue_translation('s',row,'Scout: Take 0 crates to the old station.','gpt-6-luna',i)
                    s.complete_translation(j,'Sandıkları götür.',i)
            s.close();before=hashlib.sha256(path.read_bytes()).hexdigest()
            corpus=export_corpus(path,50)
            self.assertEqual(corpus['selected'],50);self.assertTrue(corpus['target_met'])
            self.assertEqual(len({e['source'] for e in corpus['entries']}),50)
            self.assertFalse(corpus['luna_is_gold_reference'])
            self.assertEqual(sum(bool(e['luna_references']) for e in corpus['entries']),1)
            self.assertEqual(before,hashlib.sha256(path.read_bytes()).hexdigest())

    def test_percentiles_nearest_rank_and_empty_not_zero(self):
        self.assertEqual(percentiles(range(100))['p95'],94)
        self.assertIsNone(percentiles([])['p50'])

    def test_unreviewed_quality_never_reported_as_zero_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'review.csv';fields=['id','length_group']+QUALITY_FIELDS
            with path.open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerow(dict(id='one',length_group='short'))
            q=quality_summary(path)
            self.assertEqual(q['reviewed'],0);self.assertIsNone(q['groups']['all']['quality_error_rate'])
            with path.open('a',encoding='utf-8-sig',newline='') as f:
                w=csv.DictWriter(f,fieldnames=fields)
                w.writerow(dict(id='two',length_group='long',accuracy_1_5='3',naturalness_1_5='4',
                    names_error='0',negation_error='1',meaning_loss='0',incomplete='0',extra_text='0'))
            q=quality_summary(path)
            self.assertEqual(q['reviewed'],1);self.assertEqual(q['groups']['all']['quality_error_rate'],1)
