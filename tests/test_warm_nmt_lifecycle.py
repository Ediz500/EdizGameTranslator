from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from light_translation import WarmNMTClient,LocalEngineError


class WorkerLifecycleTests(unittest.TestCase):
    def folder(self,path):
        manifest=dict(engine='ct2-marian',source_lang='en',target_lang='tr',files={})
        for name in ('model.bin','source.spm','target.spm'):
            (Path(path)/name).write_bytes(b'fixture')
            manifest['files'][name]=hashlib.sha256(b'fixture').hexdigest()
        (Path(path)/'ediz_nmt.json').write_text(json.dumps(manifest))

    def test_out_of_order_worker_responses_are_matched_by_request_id(self):
        real=subprocess.Popen;starts=[]
        script="""import sys,json,time,threading
print(json.dumps({'id':0,'ready':True}),flush=True)
lock=threading.Lock()
def run(r):
 time.sleep(.12 if r['text']=='slow' else .01)
 with lock:print(json.dumps({'id':r['id'],'text':r['text']+' TR','complete':True}),flush=True)
for line in sys.stdin:threading.Thread(target=run,args=(json.loads(line),)).start()
"""
        def launch(command,**kwargs):
            starts.append(kwargs['env'])
            return real([sys.executable,'-u','-c',script],**kwargs)
        with tempfile.TemporaryDirectory() as folder,patch('light_translation.subprocess.Popen',side_effect=launch):
            self.folder(folder);c=WarmNMTClient(sys.executable,folder,threads=1)
            try:
                with ThreadPoolExecutor(2) as pool:
                    slow=pool.submit(c.translate,'slow');fast=pool.submit(c.translate,'fast')
                    self.assertEqual(fast.result()['text'],'fast TR')
                    self.assertEqual(slow.result()['text'],'slow TR')
                self.assertEqual(len(starts),1)
                self.assertEqual(starts[0]['HF_HUB_OFFLINE'],'1')
            finally:c.close()
            self.assertIsNotNone(c.process.poll())

    def test_request_timeout_stops_child_without_cloud(self):
        real=subprocess.Popen
        script="import sys,json,time;print(json.dumps({'id':0,'ready':True}),flush=True);sys.stdin.readline();time.sleep(30)"
        def launch(command,**kwargs):return real([sys.executable,'-u','-c',script],**kwargs)
        with tempfile.TemporaryDirectory() as folder,patch('light_translation.subprocess.Popen',side_effect=launch):
            self.folder(folder);c=WarmNMTClient(sys.executable,folder,threads=1,request_timeout=.1)
            with self.assertRaises(LocalEngineError):c.translate('Go!')
            c.close();
            self.assertIsNotNone(c.process.poll())
