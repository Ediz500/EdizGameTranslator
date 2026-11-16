"""Small local SQLite journal; accepted lines survive a slow/disconnected AI."""
import sqlite3
import threading
import time
import json
from pathlib import Path
from .live_sources import LiveSources


class SubtitleStore(LiveSources):
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.condition=threading.Condition(self.lock)
        self.db = sqlite3.connect(path, timeout=3, check_same_thread=False)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('''CREATE TABLE IF NOT EXISTS subtitles (
            id INTEGER PRIMARY KEY, session TEXT NOT NULL, text TEXT NOT NULL,
            first_seen_mono REAL NOT NULL, last_seen_mono REAL NOT NULL,
            observed_utc REAL NOT NULL, accepted_mono REAL NOT NULL,
            end_mono REAL, end_utc REAL, confidence REAL NOT NULL,
            reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'captured',
            translated TEXT, updated_utc REAL NOT NULL,
            queue_wait_ms REAL, translation_ms REAL)''')
        self.db.execute('CREATE INDEX IF NOT EXISTS subtitle_status ON subtitles(status)')
        # Additive migration: preserve all existing original text and budget data.
        columns={row[1] for row in self.db.execute('PRAGMA table_info(subtitles)')}
        for name,kind in (('canonical_text','TEXT'),('speaker','TEXT'),('track_key','TEXT'),('revision','INTEGER DEFAULT 0')):
            if name not in columns:self.db.execute(f'ALTER TABLE subtitles ADD COLUMN {name} {kind}')
        self.db.execute('UPDATE subtitles SET canonical_text=text WHERE canonical_text IS NULL')
        self.db.execute('''CREATE TABLE IF NOT EXISTS ocr_frames (
            id INTEGER PRIMARY KEY, session TEXT NOT NULL, captured_mono REAL NOT NULL,
            captured_utc REAL NOT NULL, raw_texts TEXT NOT NULL, raw_scores TEXT NOT NULL,
            raw_boxes TEXT)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS subtitle_observations (
            id INTEGER PRIMARY KEY, frame_id INTEGER NOT NULL REFERENCES ocr_frames(id),
            subtitle_id INTEGER REFERENCES subtitles(id), track_key TEXT, speaker TEXT,
            observed_text TEXT NOT NULL, confidence REAL NOT NULL, box TEXT, action TEXT NOT NULL)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS subtitle_revisions (
            id INTEGER PRIMARY KEY, subtitle_id INTEGER NOT NULL REFERENCES subtitles(id),
            canonical_text TEXT NOT NULL, observed_mono REAL NOT NULL, reason TEXT NOT NULL)''')
        self.db.execute('CREATE INDEX IF NOT EXISTS observation_subtitle ON subtitle_observations(subtitle_id)')
        self.db.execute('''CREATE TABLE IF NOT EXISTS translation_jobs (
            id INTEGER PRIMARY KEY, subtitle_id INTEGER NOT NULL REFERENCES subtitles(id),
            session TEXT NOT NULL, source TEXT NOT NULL, speaker TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL, translation_state TEXT NOT NULL DEFAULT 'queued',
            display_state TEXT NOT NULL DEFAULT 'not_ready', translated TEXT,
            accepted_mono REAL NOT NULL, translation_start_mono REAL, ready_mono REAL,
            display_queue_mono REAL, overlay_sent_mono REAL, visible_mono REAL,
            ended_mono REAL, duration REAL, renderer TEXT, cancel_reason TEXT,
            updated_utc REAL NOT NULL)''')
        self.db.execute('CREATE INDEX IF NOT EXISTS jobs_session_order ON translation_jobs(session,id)')
        self.db.execute('CREATE INDEX IF NOT EXISTS jobs_translation ON translation_jobs(session,translation_state,id)')
        self.db.execute('CREATE INDEX IF NOT EXISTS jobs_display ON translation_jobs(session,display_state,id)')
        job_columns={r[1] for r in self.db.execute('PRAGMA table_info(translation_jobs)')}
        self.legacy_called_column='api_called' in job_columns
        # Additive migration only. Historical billing columns/values stay in
        # existing databases; new databases do not create or track them.
        if 'translation_start_mono' not in job_columns:
            self.db.execute('ALTER TABLE translation_jobs ADD COLUMN translation_start_mono REAL')
            if 'api_start_mono' in job_columns:
                self.db.execute('UPDATE translation_jobs SET translation_start_mono=api_start_mono')
        self.db.execute('''CREATE TABLE IF NOT EXISTS render_acks (
            job_id INTEGER NOT NULL REFERENCES translation_jobs(id),renderer TEXT NOT NULL,
            seen_mono REAL NOT NULL,PRIMARY KEY(job_id,renderer))''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS translation_timings (
            job_id INTEGER PRIMARY KEY REFERENCES translation_jobs(id), metrics TEXT NOT NULL)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS transport_events (
            job_id INTEGER NOT NULL REFERENCES translation_jobs(id),transport TEXT NOT NULL,
            sent_mono REAL NOT NULL,PRIMARY KEY(job_id,transport))''')
        self.db.execute("UPDATE translation_jobs SET display_state='cancelled',cancel_reason='process_restart' WHERE display_state NOT IN ('completed','cancelled','skipped')")
        self.db.execute("UPDATE translation_jobs SET translation_state='interrupted' WHERE translation_state IN ('queued','translating')")
        self.db.execute('PRAGMA user_version=4')
        self.initialize_live_sources()
        self.db.execute("UPDATE subtitles SET status='interrupted' WHERE status IN ('queued','translating')")
        self.db.commit()

    def accept(self, session, text, first, last, utc, accepted, confidence, reason, speaker='', track_key=''):
        with self.lock, self.db:
            cursor = self.db.execute('''INSERT INTO subtitles
                (session,text,first_seen_mono,last_seen_mono,observed_utc,accepted_mono,
                 confidence,reason,updated_utc,canonical_text,speaker,track_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (session,text,first,last,utc,accepted,confidence,reason,time.time(),text,speaker,track_key))
            self.db.execute('INSERT INTO subtitle_revisions (subtitle_id,canonical_text,observed_mono,reason) VALUES (?,?,?,?)',
                            (cursor.lastrowid,text,accepted,reason))
            if track_key:
                self.db.execute('UPDATE subtitle_observations SET subtitle_id=? WHERE track_key=? AND subtitle_id IS NULL',
                                (cursor.lastrowid,track_key))
            return cursor.lastrowid

    def frame(self,session,mono,utc,texts,scores,boxes):
        with self.lock,self.db:
            return self.db.execute('''INSERT INTO ocr_frames
                (session,captured_mono,captured_utc,raw_texts,raw_scores,raw_boxes) VALUES (?,?,?,?,?,?)''',
                (session,mono,utc,json.dumps(texts,ensure_ascii=False),json.dumps(scores),json.dumps(boxes))).lastrowid

    def observation(self,frame_id,subtitle_id,track_key,speaker,text,confidence,box,action):
        with self.lock,self.db:
            self.db.execute('''INSERT INTO subtitle_observations
                (frame_id,subtitle_id,track_key,speaker,observed_text,confidence,box,action) VALUES (?,?,?,?,?,?,?,?)''',
                (frame_id,subtitle_id,track_key,speaker,text,confidence,json.dumps(box),action))

    def revise(self,row,text,mono,reason):
        with self.lock,self.db:
            self.db.execute('INSERT INTO subtitle_revisions (subtitle_id,canonical_text,observed_mono,reason) VALUES (?,?,?,?)',
                            (row,text,mono,reason))
            self.db.execute('UPDATE subtitles SET canonical_text=?,revision=revision+1,updated_utc=? WHERE id=?',
                            (text,time.time(),row))

    def seen(self, row, mono, utc):
        with self.lock, self.db:
            self.db.execute('UPDATE subtitles SET last_seen_mono=?,updated_utc=?,end_mono=NULL,end_utc=NULL WHERE id=?',
                            (mono,utc,row))

    def finish(self, row, mono, utc):
        with self.lock, self.db:
            self.db.execute('UPDATE subtitles SET end_mono=?,end_utc=? WHERE id=?', (mono,utc,row))

    def status(self, row, status, translated=None, queue_wait_ms=None, translation_ms=None):
        with self.lock, self.db:
            self.db.execute('''UPDATE subtitles SET status=?,translated=COALESCE(?,translated),
                updated_utc=?,queue_wait_ms=COALESCE(?,queue_wait_ms),
                translation_ms=COALESCE(?,translation_ms) WHERE id=?''',
                (status,translated,time.time(),queue_wait_ms,translation_ms,row))

    def enqueue_translation(self,session,row,source,model,accepted):
        with self.lock,self.db:
            # Revisions of one utterance replace unclaimed work in place. An
            # identical callback is idempotent even after claim/completion.
            existing=self.db.execute('''SELECT id,source,translation_state,model FROM translation_jobs
                WHERE session=? AND subtitle_id=? ORDER BY id DESC LIMIT 1''',(session,row)).fetchone()
            if existing:
                from ediz_game_translator.capture.subtitle_tracking import equivalent
                if existing[3]!=model:raise ValueError('Aynı altyazının modeli değiştirilemez.')
                if equivalent(existing[1],source):return existing[0]
                if existing[2]=='queued':
                    self.db.execute('UPDATE translation_jobs SET source=?,updated_utc=? WHERE id=?',
                                    (source,time.time(),existing[0]))
                    return existing[0]
            speaker=self.db.execute('SELECT speaker FROM subtitles WHERE id=?',(row,)).fetchone()[0] or ''
            fields=['session','subtitle_id','source','speaker','model','accepted_mono','updated_utc']
            values=[session,row,source,speaker,model,accepted,time.time()]
            if self.legacy_called_column and model.startswith('local:'):
                fields.append('api_called');values.append(0)  # Existing history is never rewritten.
            job=self.db.execute('INSERT INTO translation_jobs ('+','.join(fields)+') VALUES ('+','.join('?' for _ in values)+')',values).lastrowid
            self.db.execute("UPDATE subtitles SET status='queued' WHERE id=?",(row,))
            self.condition.notify_all()
            return job

    def record_timing(self,job,metrics):
        # Explicit local numeric timings only; never persist credentials.
        import math
        safe={k:float(v) for k,v in metrics.items() if k in
              ('total_ms','engine_init_ms','processing_ms','roundtrip_ms','capacity_wait_ms')
              and isinstance(v,(int,float)) and math.isfinite(v) and v>=0}
        with self.lock,self.db:
            self.db.execute('INSERT OR REPLACE INTO translation_timings VALUES (?,?)',
                            (job,json.dumps(safe)))

    def refresh_pending_source(self,session,row,source):
        # OCR corrections improve only unclaimed work; never retranslate an
        # in-flight/completed request merely to fix punctuation or glyph noise.
        with self.lock,self.db:
            self.db.execute('''UPDATE translation_jobs SET source=?,updated_utc=?
                WHERE session=? AND subtitle_id=? AND translation_state='queued'
                AND display_state!='cancelled' ''',(source,time.time(),session,row))

    def claim_translation(self,session,now):
        with self.lock,self.db:
            live=session in self.live_options
            if live:self._expire_sources(session,now)
            current=" AND EXISTS(SELECT 1 FROM live_sources s WHERE s.subtitle_id=j.subtitle_id AND s.session=j.session AND s.active=1)" if live else ''
            cursor=self.db.execute("""SELECT id,subtitle_id,source,model,accepted_mono FROM translation_jobs j
                WHERE session=? AND translation_state='queued' AND display_state!='cancelled'
                AND NOT EXISTS(SELECT 1 FROM translation_jobs active WHERE active.session=j.session
                    AND active.subtitle_id=j.subtitle_id AND active.translation_state='translating')
                """+current+" ORDER BY id LIMIT 1",(session,))
            row=cursor.fetchone()
            if row is None:return None
            self.db.execute("UPDATE translation_jobs SET translation_state='translating',translation_start_mono=?,updated_utc=? WHERE id=?",(now,time.time(),row[0]))
            self.db.execute("UPDATE subtitles SET status='translating',queue_wait_ms=? WHERE id=?",((now-row[4])*1000,row[1]))
            return dict(zip(('id','subtitle_id','source','model','accepted_mono'),row))

    def context_before(self,job):
        with self.lock:
            return [r[0] for r in reversed(self.db.execute("""SELECT source FROM translation_jobs
                WHERE session=(SELECT session FROM translation_jobs WHERE id=?) AND id<?
                AND subtitle_id!=(SELECT subtitle_id FROM translation_jobs WHERE id=?)
                ORDER BY id DESC LIMIT 2""",(job,job,job)).fetchall())]

    def complete_translation(self,job,text,now,duration=None):
        from ediz_game_translator.subtitles.subtitle_display import reading_seconds
        with self.lock,self.db:
            row=self.db.execute('SELECT subtitle_id,speaker,display_state,translation_start_mono,session FROM translation_jobs WHERE id=?',(job,)).fetchone()
            if row is None:raise ValueError('Çeviri işi bulunamadı.')
            if row[1] and text.casefold().startswith(row[1].casefold()+':'):text=text[len(row[1])+1:].lstrip()
            duration=(None if row[4] in self.live_options else reading_seconds(text)) if duration is None else duration
            state='cancelled' if row[2]=='cancelled' else 'waiting'
            newer=self.db.execute('SELECT 1 FROM translation_jobs WHERE subtitle_id=? AND id>? LIMIT 1',(row[0],job)).fetchone()
            model=self.db.execute('SELECT model FROM translation_jobs WHERE id=?',(job,)).fetchone()[0]
            if state!='cancelled' and model.startswith('local:') and newer:state='skipped'
            self.db.execute('''UPDATE translation_jobs SET translation_state='completed',display_state=?,translated=?,
                ready_mono=?,display_queue_mono=?,duration=?,updated_utc=? WHERE id=?''',
                (state,text,now,now,duration,time.time(),job))
            self.db.execute("UPDATE subtitles SET status='translated',translated=?,translation_ms=?,updated_utc=? WHERE id=?",
                (text,(now-row[3])*1000 if row[3] is not None else None,time.time(),row[0]))
            self.condition.notify_all()

    def fail_translation(self,job,now):
        with self.lock,self.db:
            self.db.execute("UPDATE translation_jobs SET translation_state='error',display_state=CASE WHEN display_state='cancelled' THEN 'cancelled' ELSE 'skipped' END,ready_mono=?,updated_utc=? WHERE id=?",(now,time.time(),job))
            self.db.execute("UPDATE subtitles SET status='translation_error' WHERE id=(SELECT subtitle_id FROM translation_jobs WHERE id=?)",(job,))
            self.condition.notify_all()

    def offer_next(self,session,now,ready_first=False):
        with self.lock,self.db:
            query="""SELECT id,translated,speaker,duration,display_state,ready_mono FROM translation_jobs
                WHERE session=? AND display_state IN ('not_ready','waiting') ORDER BY id LIMIT 1"""
            if ready_first:
                query="""SELECT id,translated,speaker,duration,display_state,ready_mono FROM translation_jobs
                    WHERE session=? AND display_state='waiting' AND ready_mono<=?
                    ORDER BY ready_mono,id LIMIT 1"""
            row=self.db.execute(query,(session,now) if ready_first else (session,)).fetchone()
            if row is None or row[4]!='waiting' or row[5]>now:return None
            self.db.execute("UPDATE translation_jobs SET display_state='offered',updated_utc=? WHERE id=?",(time.time(),row[0]))
            return dict(id=row[0],text=row[1],speaker=row[2],duration=row[3])

    def ack_observation(self,job,now,renderer):
        with self.lock,self.db:
            self.db.execute('''INSERT OR IGNORE INTO render_acks(job_id,renderer,seen_mono)
                SELECT id,?,? FROM translation_jobs WHERE id=? AND display_state IN ('offered','showing')''',(renderer,now,job))

    def transport_sent(self,ids,transport,now):
        with self.lock,self.db:
            self.db.executemany('INSERT OR IGNORE INTO transport_events VALUES (?,?,?)',
                                [(job,transport,now) for job in ids])

    def display_event(self,job,event,now,renderer=None):
        if event not in ('sent','visible','ended'):raise ValueError('Gösterim olayı geçersiz.')
        with self.lock,self.db:
            if event=='sent':
                self.db.execute("UPDATE translation_jobs SET overlay_sent_mono=? WHERE id=? AND overlay_sent_mono IS NULL AND display_state IN ('offered','showing')",(now,job))
            elif event=='visible':
                self.db.execute('INSERT OR IGNORE INTO render_acks(job_id,renderer,seen_mono) VALUES (?,?,?)',(job,renderer,now))
                self.db.execute("UPDATE translation_jobs SET visible_mono=COALESCE(visible_mono,?),renderer=COALESCE(renderer,?),display_state='showing' WHERE id=? AND display_state='offered'",(now,renderer,job))
            else:
                self.db.execute("UPDATE translation_jobs SET ended_mono=?,display_state='completed' WHERE id=? AND display_state='showing'",(now,job))
            self.condition.notify_all()

    def queue_stats(self,session):
        with self.lock:
            row=self.db.execute('''SELECT count(*),COALESCE(sum(duration),0) FROM translation_jobs
                WHERE session=? AND display_state='waiting' ''',(session,)).fetchone()
            pending=self.db.execute("SELECT count(*) FROM translation_jobs WHERE session=? AND translation_state IN ('queued','translating') AND display_state!='cancelled'",(session,)).fetchone()[0]
            return dict(waiting=row[0],backlog_seconds=row[1]/3,translation_pending=pending,overloaded=row[0]+pending>=100)

    def cancel_session(self,session,reason='user_stop'):
        with self.lock,self.db:
            self.db.execute('UPDATE live_sources SET active=0,ended_mono=COALESCE(ended_mono,?),reason=? WHERE session=? AND active=1',(time.monotonic(),reason,session))
            self.db.execute("UPDATE translation_jobs SET display_state='cancelled',cancel_reason=?,updated_utc=? WHERE session=? AND display_state NOT IN ('completed','cancelled','skipped')",(reason,time.time(),session))
            self.db.execute("UPDATE translation_jobs SET translation_state='cancelled' WHERE session=? AND translation_state='queued'",(session,))
            self.condition.notify_all()

    def session_metrics(self,session):
        import math,statistics
        with self.lock:
            records=self.db.execute('''SELECT model,accepted_mono,translation_start_mono,ready_mono,overlay_sent_mono,visible_mono,translation_state
                FROM translation_jobs WHERE session=? ORDER BY id DESC LIMIT 4096''',(session,)).fetchall()
            def percentiles(values):
                v=sorted(values)
                return dict(p50=statistics.median(v),p95=v[max(0,math.ceil(.95*len(v))-1)]) if v else {}
            stages={}
            stages['ocr_accept_ms']=percentiles([(a-f)*1000 for a,f in self.db.execute(
                'SELECT accepted_mono,first_seen_mono FROM subtitles WHERE session=? ORDER BY id DESC LIMIT 4096',(session,))])
            browser=self.db.execute("SELECT j.accepted_mono,j.ready_mono,a.seen_mono FROM translation_jobs j JOIN render_acks a ON a.job_id=j.id WHERE j.session=? AND a.renderer='browser_dom_ack' ORDER BY j.id DESC LIMIT 4096",(session,)).fetchall()
            stages['accept_to_browser_report_ms']=percentiles([(v-a)*1000 for a,r,v in browser])
            stages['ready_to_browser_report_ms']=percentiles([(v-r)*1000 for a,r,v in browser if r is not None])
            for name,a,b in [('ready_to_http_ms',3,4),('accept_to_renderer_ms',1,5),('display_wait_ms',3,5)]:
                stages[name]=percentiles([(r[b]-r[a])*1000 for r in records if r[a] is not None and r[b] is not None])
            stages['translation_queue_ms']=percentiles([(r[2]-r[1])*1000 for r in records if r[2] is not None])
            stages['translation_total_ms']=percentiles([(r[3]-r[2])*1000 for r in records if r[2] is not None and r[3] is not None and r[6]=='completed'])
            measured=[json.loads(r[0]) for r in self.db.execute('''SELECT t.metrics FROM translation_timings t
                JOIN translation_jobs j ON j.id=t.job_id WHERE j.session=? ORDER BY j.id DESC LIMIT 4096''',(session,))]
            for stage in ('engine_init_ms','processing_ms','roundtrip_ms','capacity_wait_ms'):
                stages[stage]=percentiles([r[stage] for r in measured if stage in r])
            stages['first_seen_to_renderer_ms']=percentiles([(v-f)*1000 for f,v in self.db.execute('''SELECT s.first_seen_mono,j.visible_mono
                FROM translation_jobs j JOIN subtitles s ON s.id=j.subtitle_id WHERE j.session=? AND j.visible_mono IS NOT NULL''',(session,))])
            counts=dict(self.db.execute('SELECT display_state,count(*) FROM translation_jobs WHERE session=? GROUP BY display_state',(session,)).fetchall())
            models=[]
            for model, in self.db.execute('SELECT DISTINCT model FROM translation_jobs WHERE session=?',(session,)):
                samples=[(r[3]-r[2])*1000 for r in records if r[0]==model and r[2] is not None and r[3] is not None and r[6]=='completed']
                models.append(dict(model=model,translation_ms=percentiles(samples),sample_count=len(samples)))
            total,translated,visible=self.db.execute("SELECT count(*),COALESCE(sum(translation_state='completed'),0),COALESCE(sum(visible_mono IS NOT NULL),0) FROM translation_jobs WHERE session=?",(session,)).fetchone()
            return dict(translation_jobs=total,translated=translated,renderer_reported_visible=visible,
                display_counts=counts,models=models,stages_ms=stages,sample_limit=4096,physical_tv_verified=False)

    def close(self):
        with self.lock:
            self.db.execute("UPDATE translation_jobs SET display_state='cancelled',cancel_reason=COALESCE(cancel_reason,'app_close') WHERE display_state NOT IN ('completed','cancelled','skipped')")
            self.db.execute("UPDATE subtitles SET status='not_completed' WHERE status IN ('queued','translating')")
            self.db.commit()
            self.db.close()
