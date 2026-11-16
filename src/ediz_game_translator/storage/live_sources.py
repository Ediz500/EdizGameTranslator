"""Source visibility journal. Completed translations are history, never a playlist."""
import json
import math
import time


class LiveSources:
    def initialize_live_sources(self):
        self.live_options={}
        self.db.execute('''CREATE TABLE IF NOT EXISTS live_sources (
            subtitle_id INTEGER PRIMARY KEY REFERENCES subtitles(id),session TEXT NOT NULL,
            track_key TEXT NOT NULL,canonical TEXT NOT NULL,speaker TEXT NOT NULL,
            bounds TEXT,last_seen REAL NOT NULL,absent_since REAL,missed INTEGER DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,ended_mono REAL,reason TEXT,
            frame_width INTEGER DEFAULT 1920,frame_height INTEGER DEFAULT 1080,manual_until REAL)''')
        self.db.execute('CREATE INDEX IF NOT EXISTS live_session ON live_sources(session,active)')
        self.db.execute('''CREATE TABLE IF NOT EXISTS render_removals (
            job_id INTEGER NOT NULL REFERENCES translation_jobs(id),renderer TEXT NOT NULL,
            hidden_mono REAL NOT NULL,PRIMARY KEY(job_id,renderer))''')
        # No source from a previous process can become a current caption.
        self.db.execute("UPDATE live_sources SET active=0,reason='process_restart' WHERE active=1")

    def enable_live_session(self,session,debounce=.12,stale=.6):
        if not .05<=debounce<=.3 or not .3<=stale<=2:raise ValueError('Geçersiz kaynak zaman sınırı.')
        with self.lock:self.live_options[session]=dict(debounce=debounce,stale=stale)

    def _end_live_source(self,row,now,reason):
        self.db.execute('UPDATE live_sources SET active=0,ended_mono=?,reason=? WHERE subtitle_id=? AND active=1',(now,reason,row))
        self.db.execute('''UPDATE translation_jobs SET display_state='cancelled',cancel_reason=?,ended_mono=COALESCE(ended_mono,?),
            translation_state=CASE WHEN translation_state='queued' THEN 'cancelled' ELSE translation_state END
            WHERE subtitle_id=? AND display_state NOT IN ('completed','cancelled','skipped')''',(reason,now,row))

    def publish_sources(self,session,entries,sample_mono,*,decided_mono=None,retired=(),frame_size=(1920,1080)):
        """Called after OCR/storage and before dispatch. Entries contain no translation."""
        from ediz_game_translator.capture.subtitle_tracking import equivalent
        now=sample_mono if decided_mono is None else decided_mono
        seen={e['subtitle_id'] for e in entries};retired=set(retired)
        with self.lock,self.db:
            for row,key in self.db.execute('SELECT subtitle_id,track_key FROM live_sources WHERE session=? AND active=1',(session,)).fetchall():
                if row in seen:continue
                self.db.execute('UPDATE live_sources SET absent_since=COALESCE(absent_since,?),missed=missed+1 WHERE subtitle_id=?',(sample_mono,row))
                if key in retired:self._end_live_source(row,now,'source_replaced')
            for e in entries:
                bounds=e.get('bounds')
                if bounds is not None:
                    if len(bounds)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=1 for v in bounds):bounds=None
                    elif not(bounds[0]<bounds[2] and bounds[1]<bounds[3]):bounds=None
                row=e['subtitle_id'];old=self.db.execute('SELECT canonical,active,reason FROM live_sources WHERE subtitle_id=?',(row,)).fetchone()
                if old and not equivalent(old[0],e['canonical']):
                    self.db.execute("UPDATE translation_jobs SET display_state='skipped',cancel_reason='source_revised',ended_mono=? WHERE subtitle_id=? AND translation_state='completed' AND display_state NOT IN ('completed','cancelled','skipped')",(now,row))
                if old and not old[1] and old[2]=='ocr_stale':
                    self.db.execute("UPDATE translation_jobs SET display_state='waiting',cancel_reason=NULL,ended_mono=NULL WHERE subtitle_id=? AND translation_state='completed' AND cancel_reason='ocr_stale'",(row,))
                self.db.execute('''INSERT INTO live_sources
                    (subtitle_id,session,track_key,canonical,speaker,bounds,last_seen,frame_width,frame_height,manual_until)
                    VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(subtitle_id) DO UPDATE SET
                    canonical=excluded.canonical,speaker=excluded.speaker,bounds=excluded.bounds,last_seen=excluded.last_seen,
                    absent_since=NULL,missed=0,active=1,ended_mono=NULL,reason=NULL,
                    frame_width=excluded.frame_width,frame_height=excluded.frame_height,manual_until=excluded.manual_until''',
                    (row,session,e['track_key'],e['canonical'],e.get('speaker',''),json.dumps(bounds) if bounds else None,
                     sample_mono,int(frame_size[0]),int(frame_size[1]),e.get('manual_until')))
            self._expire_sources(session,now)
            self.condition.notify_all()

    def _expire_sources(self,session,now):
        config=self.live_options.get(session,dict(debounce=.12,stale=.6))
        for row,last,absent,missed,manual in self.db.execute('SELECT subtitle_id,last_seen,absent_since,missed,manual_until FROM live_sources WHERE session=? AND active=1',(session,)).fetchall():
            if manual is not None:
                if now>=manual:self._end_live_source(row,now,'manual_end')
            elif missed>=2 and absent is not None and now-absent>=config['debounce']:
                self._end_live_source(row,now,'source_gone')
            elif now-last>config['stale']:self._end_live_source(row,now,'ocr_stale')

    def live_blocks(self,session,now):
        from ediz_game_translator.capture.subtitle_tracking import equivalent
        with self.lock,self.db:
            self._expire_sources(session,now)
            cursor=self.db.execute('''SELECT j.id,j.subtitle_id,j.source,j.translated,j.visible_mono,
                s.canonical,s.speaker,s.bounds,s.frame_width,s.frame_height,j.display_state,j.cancel_reason
                FROM translation_jobs j JOIN live_sources s ON s.subtitle_id=j.subtitle_id
                WHERE j.session=? AND s.session=? AND s.active=1 AND j.translation_state='completed'
                AND j.ready_mono<=? ORDER BY j.id DESC''',(session,session,now))
            blocks=[];seen=set()
            for job,row,source,text,visible,canonical,speaker,bounds,w,h,state,reason in cursor.fetchall():
                if row in seen or state in ('cancelled','skipped','completed') or not equivalent(source,canonical):continue
                seen.add(row)
                if state=='waiting':self.db.execute("UPDATE translation_jobs SET display_state='offered' WHERE id=?",(job,))
                blocks.append(dict(id=job,subtitle_id=row,text=text,speaker=speaker,started=visible,
                    bounds=json.loads(bounds) if bounds else None,source_size=[w,h],source=canonical))
            blocks.sort(key=lambda b:(b['bounds'][1] if b['bounds'] else 1,b['subtitle_id']))
            return blocks[:3]

    def live_stats(self,session,now):
        with self.lock,self.db:
            self._expire_sources(session,now)
            active=self.db.execute('SELECT count(*) FROM live_sources WHERE session=? AND active=1',(session,)).fetchone()[0]
            pending=self.db.execute("SELECT count(*) FROM translation_jobs j JOIN live_sources s ON s.subtitle_id=j.subtitle_id WHERE j.session=? AND s.active=1 AND j.translation_state IN ('queued','translating')",(session,)).fetchone()[0]
            return dict(active_sources=active,translation_pending=pending,waiting=0,backlog_seconds=0,overloaded=pending>=20)

    def ack_live_removal(self,session,job,now,renderer):
        with self.lock,self.db:
            row=self.db.execute('SELECT ended_mono FROM translation_jobs WHERE id=? AND session=?',(job,session)).fetchone()
            if row is None or row[0] is None:return False
            self.db.execute('INSERT OR IGNORE INTO render_removals VALUES (?,?,?)',(job,renderer,now))
            return True

    def removal_latencies(self,session):
        with self.lock:
            return [dict(renderer=r,ms=max(0,(hidden-origin)*1000)) for r,hidden,origin in self.db.execute('''
                SELECT r.renderer,r.hidden_mono,COALESCE(s.absent_since,j.ended_mono) FROM render_removals r
                JOIN translation_jobs j ON j.id=r.job_id JOIN live_sources s ON s.subtitle_id=j.subtitle_id
                WHERE j.session=? AND COALESCE(s.absent_since,j.ended_mono) IS NOT NULL''',(session,))]
