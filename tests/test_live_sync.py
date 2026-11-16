"""Current source → current translation, with no presentation backlog."""
from bootstrap import configure_paths
configure_paths()
from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from PIL import Image
from ediz_game_translator.storage.subtitle_store import SubtitleStore
from ediz_game_translator.subtitles.live_display import LiveDisplayManager
from ediz_game_translator.subtitles.overlay_server import SharedOverlayState
from ediz_game_translator.capture.capture_pipeline import CaptureRunner,DiagnosticLog
from ediz_game_translator.storage.subtitle_styles import DEFAULT_STYLE,with_style,style_for,valid_style
from ediz_game_translator.storage.region_profiles import with_region,rename_game
from ediz_game_translator.subtitles.layout import arrange_blocks,viewport_rect
from ediz_game_translator.core import DEFAULTS


class LiveSyncTests(unittest.TestCase):
    def setUp(self):
        self.store=SubtitleStore(':memory:');self.now=[10.]
        self.manager=LiveDisplayManager(self.store,'s',clock=lambda:self.now[0])
    def tearDown(self):self.store.close()
    def source(self,text,speaker='',bounds=None):
        n=self.now[0]
        row=self.store.accept('s',text,n,n,0,n,.99,'fixture',speaker=speaker)
        return dict(subtitle_id=row,track_key=str(row),canonical=text,speaker=speaker,bounds=bounds)
    def observe(self,*entries,retired=()):self.store.publish_sources('s',entries,self.now[0],retired=retired)
    def job(self,entry,text):
        j=self.store.enqueue_translation('s',entry['subtitle_id'],entry['canonical'],'local:ct2-marian',self.now[0])
        self.store.complete_translation(j,text,self.now[0]);return j
    def texts(self):return [b['text'] for b in self.manager.snapshot()['blocks']]

    def test_single_dropout_recovers_but_two_blanks_remove_after_debounce(self):
        a=self.source('Scout: Stay here.','Scout');self.observe(a);j=self.job(a,'Burada kal.')
        self.assertEqual(self.texts(),['Burada kal.'])
        self.now[0]=10.04;self.observe();self.assertEqual(self.texts(),['Burada kal.'])
        self.now[0]=10.08;self.observe(a);self.assertEqual(self.texts(),['Burada kal.'])
        self.now[0]=10.12;self.observe();self.now[0]=10.18;self.observe()
        self.assertEqual(self.texts(),['Burada kal.'])
        self.now[0]=10.25;self.assertEqual(self.texts(),[])
        self.assertEqual(self.store.db.execute('SELECT translated FROM translation_jobs WHERE id=?',(j,)).fetchone()[0],'Burada kal.')

    def test_ready_B_never_waits_for_A_and_late_A_remains_only_in_history(self):
        a=self.source('A long source sentence.');self.observe(a)
        old=self.store.enqueue_translation('s',a['subtitle_id'],a['canonical'],'local:ct2-marian',10)
        self.store.claim_translation('s',10)
        self.now[0]=10.05;b=self.source('The next source sentence.');self.observe(b,retired=[a['track_key']])
        self.job(b,'Yeni replik.');self.assertEqual(self.texts(),['Yeni replik.'])
        self.store.complete_translation(old,'Eski replik.',10.06)
        self.assertEqual(self.texts(),['Yeni replik.'])
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM translation_jobs').fetchone()[0],2)
        self.assertEqual(self.manager.snapshot()['waiting'],0)

    def test_three_real_sources_independent_and_no_read_clock_fields(self):
        entries=[self.source(f'Speaker {i}: Stay here.','Speaker '+str(i),[.2,.2+i*.2,.8,.25+i*.2]) for i in range(3)]
        self.observe(*entries)
        jobs=[self.job(e,f'Replik {i}.') for i,e in enumerate(entries)]
        blocks=self.manager.snapshot()['blocks'];self.assertEqual(len(blocks),3)
        self.assertTrue(all(not({'remaining','duration','speed'}&set(b)) for b in blocks))
        for j in jobs:self.manager.ack(j,'browser_dom_ack')
        starts={b['id']:b['started'] for b in self.manager.snapshot()['blocks']}
        self.now[0]=10.05;self.observe(entries[0],entries[2],retired=[entries[1]['track_key']])
        self.assertEqual(self.texts(),['Replik 0.','Replik 2.'])
        self.assertEqual({b['id']:b['started'] for b in self.manager.snapshot()['blocks']},{j:t for j,t in starts.items() if j!=jobs[1]})

    def test_extension_hides_old_fragment_until_matching_full_result(self):
        a=self.source('Scout: We should check the','Scout');self.observe(a);self.job(a,'Bakmalıyız.')
        self.assertEqual(self.texts(),['Bakmalıyız.'])
        self.now[0]=10.04;full=dict(a,canonical='Scout: We should check the station.')
        self.store.revise(a['subtitle_id'],full['canonical'],10.04,'extension');self.observe(full)
        self.assertEqual(self.texts(),[])
        self.job(full,'İstasyonu kontrol etmeliyiz.')
        self.assertEqual(self.texts(),['İstasyonu kontrol etmeliyiz.'])

    def test_equivalent_punctuation_keeps_existing_result_without_dispatch(self):
        a=self.source('Scout: Stay close.','Scout');self.observe(a);j=self.job(a,'Yakında kal.')
        self.now[0]=10.04;self.observe(dict(a,canonical='Scout: Stay close,'))
        self.assertEqual(self.texts(),['Yakında kal.'])
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM translation_jobs').fetchone()[0],1)

    def test_stale_ocr_is_fail_closed_and_pending_old_work_not_claimed(self):
        a=self.source('The source.');self.observe(a)
        self.store.enqueue_translation('s',a['subtitle_id'],a['canonical'],'local:ct2-marian',10)
        self.now[0]=10.61
        self.assertEqual(self.texts(),[]);self.assertIsNone(self.store.claim_translation('s',self.now[0]))

    def test_hidden_renderer_latency_and_generation_are_measured(self):
        a=self.source('Scout: Stay here.','Scout');self.observe(a);j=self.job(a,'Burada kal.')
        self.manager.ack(j,'browser_dom_ack')
        self.now[0]=10.04;self.observe();self.now[0]=10.10;self.observe();self.now[0]=10.17
        self.assertEqual(self.texts(),[])
        self.assertEqual(self.manager.removed([j],'browser_dom_ack'),1)
        metric=self.store.removal_latencies('s')[0]
        self.assertAlmostEqual(metric['ms'],130)

    def test_legacy_called_default_is_zero_only_for_new_local_jobs(self):
        self.store.db.execute('ALTER TABLE translation_jobs ADD COLUMN api_called INTEGER DEFAULT 1')
        self.store.legacy_called_column=True
        a=self.source('Source.');self.observe(a);j=self.job(a,'Çeviri.')
        self.assertEqual(self.store.db.execute('SELECT api_called FROM translation_jobs WHERE id=?',(j,)).fetchone()[0],0)

    def test_manual_example_has_local_tag_and_cannot_override_live_session(self):
        state=SharedOverlayState();state.set('Örnek.')
        self.assertEqual(state.manager.store.db.execute('SELECT model FROM translation_jobs').fetchone()[0],'local:manual')
        state.bind(self.store,'s',live=True)
        self.assertFalse(state.set('Yanlış örnek.'));state.clear();state.close()

    def test_mask_survives_one_blank_but_confirmed_gap_removes_both(self):
        a=self.source('Scout: Stay close.','Scout',[.2,.8,.8,.9]);self.observe(a);j=self.job(a,'Yakında kal.')
        self.now[0]=10.04;self.observe()
        blocks=arrange_blocks(self.manager.snapshot()['blocks'],DEFAULT_STYLE)
        self.assertEqual([b['id'] for b in blocks],[j]);self.assertIn('mask_rect',blocks[0])
        self.now[0]=10.08;self.observe(a);self.assertEqual(self.texts(),['Yakında kal.'])
        self.now[0]=10.12;self.observe();self.now[0]=10.18;self.observe();self.now[0]=10.25
        self.assertEqual(arrange_blocks(self.manager.snapshot()['blocks'],DEFAULT_STYLE),[])

    def test_single_slow_blank_can_hit_independent_ocr_stale_limit(self):
        a=self.source('The source.');self.observe(a);self.job(a,'Çeviri.')
        self.now[0]=10.55;self.observe();self.assertEqual(self.texts(),['Çeviri.'])
        self.now[0]=10.61
        self.assertEqual(arrange_blocks(self.manager.snapshot()['blocks'],DEFAULT_STYLE),[])
        self.assertEqual(self.store.db.execute('SELECT reason FROM live_sources').fetchone()[0],'ocr_stale')

    def test_fast_A_to_B_has_neither_old_text_nor_mask_while_B_is_pending(self):
        a=self.source('First source.',bounds=[.2,.8,.8,.9]);self.observe(a);self.job(a,'Eski A.')
        self.now[0]=10.04;b=self.source('Next source.',bounds=[.2,.8,.8,.9]);self.observe(b,retired=[a['track_key']])
        self.assertEqual(arrange_blocks(self.manager.snapshot()['blocks'],DEFAULT_STYLE),[])
        self.job(b,'Yeni B.');blocks=arrange_blocks(self.manager.snapshot()['blocks'],DEFAULT_STYLE)
        self.assertEqual([x['text'] for x in blocks],['Yeni B.']);self.assertIn('mask_rect',blocks[0])


class LivePipelineTests(unittest.TestCase):
    def test_actual_filter_pipeline_preserves_A_B_A_and_different_speakers(self):
        store=SubtitleStore(':memory:');clock=[10.];texts=['Scout: We should leave now.'];jobs=[]
        def accepted(row,text,now):jobs.append(store.enqueue_translation('s',row,text,'local:ct2-marian',now))
        image=Image.new('RGB',(960,540),'#223344')
        with patch('ediz_game_translator.capture.capture_pipeline.time.perf_counter',side_effect=lambda:clock[0]):
            runner=CaptureRunner(lambda:image,lambda im:im,lambda im:SimpleNamespace(txts=texts[:],scores=[.99],boxes=None),store,'s',DiagnosticLog(),lambda:None,accepted,live=True)
            runner.step();clock[0]=10.04;texts[:]=['Scout: Stop right there.'];runner.step()
            clock[0]=10.08;texts[:]=['Scout: We should leave now.'];runner.step()
            self.assertEqual(len(jobs),3)
            self.assertEqual(store.db.execute('SELECT count(*) FROM live_sources WHERE active=1').fetchone()[0],1)
            clock[0]=10.12;texts[:]=['Pilot: I see them.'];runner.step()
            self.assertEqual(len(jobs),4)
            clock[0]=10.2;runner.step();clock[0]=10.3;runner.step()
            self.assertEqual(store.db.execute('SELECT count(*) FROM live_sources WHERE active=1').fetchone()[0],1)
        store.close()

    def test_crop_coordinates_map_to_full_frame_and_raw_pixels_are_unchanged(self):
        store=SubtitleStore(':memory:');image=Image.new('RGB',(960,540),'#223344')
        result=SimpleNamespace(txts=['Scout: Stay here.'],scores=[.99],boxes=[[[100,20],[600,20],[600,50],[100,50]]])
        runner=CaptureRunner(lambda:image,lambda im:im.crop((96,216,864,378)),lambda im:result,store,'s',DiagnosticLog(),lambda:None,lambda *args:None,live=True,crop_rect=(.1,.4,.9,.7))
        runner.step();bounds=json.loads(store.db.execute('SELECT bounds FROM live_sources').fetchone()[0])
        self.assertAlmostEqual(bounds[0],.1+100/960);self.assertAlmostEqual(bounds[1],.4+20/540)
        self.assertEqual(image.getpixel((196,236)),(34,51,68));store.close()


class StyleAndLayoutTests(unittest.TestCase):
    def test_each_game_keeps_ocr_and_mask_on_rename(self):
        settings=with_region(deepcopy(DEFAULTS),'One',(.1,.2,.9,.4))
        style=dict(DEFAULT_STYLE,mask_rect=[.2,.3,.8,.45],speaker_color='#80A7FF')
        settings=with_style(settings,'One',style);settings=with_region(settings,'Two',(.1,.5,.9,.9))
        self.assertNotEqual(style_for(settings,'One')['mask_rect'],style_for(settings,'Two')['mask_rect'])
        renamed=rename_game(settings,'One','Renamed')
        self.assertEqual(style_for(renamed,'Renamed'),style)
        self.assertNotIn('one',renamed['subtitle_profiles'])

    def test_style_rejects_unknown_fields_and_invalid_colors(self):
        for change in ({'speaker_color':'url(secret)'},{'api_key':'dummy'},{'show_speaker':1},{'mask_rect':[0,0,2,1]}):
            with self.assertRaises(ValueError):valid_style(dict(DEFAULT_STYLE,**change))

    def test_mask_covers_trusted_source_and_uses_fixed_fallback_without_boxes(self):
        source=[.2,.8,.8,.9];blocks=arrange_blocks([dict(id=1,text='Çeviri.',speaker='Scout',bounds=source)],DEFAULT_STYLE)
        rect=blocks[0]['mask_rect']
        self.assertLessEqual(rect[0],source[0]);self.assertGreaterEqual(rect[2],source[2])
        self.assertLessEqual(rect[1],source[1]);self.assertGreaterEqual(rect[3],source[3])
        fallback=arrange_blocks([dict(id=2,text='Çeviri.',speaker='',bounds=None)],DEFAULT_STYLE)[0]['mask_rect']
        for actual,expected in zip(fallback,DEFAULT_STYLE['mask_rect']):self.assertAlmostEqual(actual,expected)

    def test_letterboxed_viewports_and_overlapping_three_sources_stay_in_bounds(self):
        rect=viewport_rect([0,0,1,1],1280,1024)
        self.assertEqual(rect,(0,152,1280,872))
        blocks=[dict(id=i,text='Uzun bir konuşma. '*25,speaker='Scout',bounds=[.2,.8,.8,.9]) for i in range(3)]
        result=arrange_blocks(blocks,dict(DEFAULT_STYLE,font_size=72))
        self.assertEqual(len(result),3)
        for b in result:
            l,t,r,bottom=b['mask_rect'];self.assertTrue(0<=l<r<=1 and 0<=t<bottom<=1)
