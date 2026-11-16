"""Compact masks, source coverage and source-scoped position stability."""
from bootstrap import configure_paths
configure_paths()
from copy import deepcopy
import unittest
from unittest.mock import patch
from ediz_game_translator.subtitles.layout import VisualLayout,arrange_blocks,viewport_rect,_font
from ediz_game_translator.storage.subtitle_styles import DEFAULT_STYLE


def block(text='Burada kal.',speaker='Scout',bounds=None,job=1,source_size=(960,540)):
    return dict(id=job,subtitle_id=job,text=text,speaker=speaker,bounds=bounds or [.4,.8,.6,.85],source_size=list(source_size))


def covers(outer,inner):
    return outer[0]<=inner[0]+1e-9 and outer[1]<=inner[1]+1e-9 and outer[2]+1e-9>=inner[2] and outer[3]+1e-9>=inner[3]


class VisualLayoutTests(unittest.TestCase):
    def setUp(self):self.layout=VisualLayout();self.style=deepcopy(DEFAULT_STYLE)
    def arrange(self,*rows,generation='s'):return self.layout.arrange(rows,self.style,generation)

    def test_short_translation_mask_is_compact_and_covers_full_english_box(self):
        b=block('Git!',bounds=[.43,.82,.57,.86]);out=self.arrange(b)[0]
        self.assertLess(out['mask_rect'][2]-out['mask_rect'][0],.25)
        self.assertTrue(covers(out['mask_rect'],b['bounds']))
        self.assertTrue(covers(out['mask_rect'],out['body_rect']))

    def test_long_english_short_turkish_still_masks_entire_source(self):
        b=block('Tamam.',bounds=[.13,.78,.87,.85]);out=self.arrange(b)[0]
        self.assertTrue(covers(out['mask_rect'],b['bounds']))
        self.assertGreaterEqual(out['mask_rect'][2]-out['mask_rect'][0],.74)

    def test_short_english_long_turkish_wraps_without_clipping(self):
        b=block('Bu uzun cümlede Türkçe karakterler ve anlaşılır satır kırılması korunmalıdır. '*5,bounds=[.44,.82,.56,.86])
        out=self.arrange(b)[0];self.assertGreater(len(out['display_lines']),1)
        available=(out['body_rect'][2]-out['body_rect'][0])*1920
        self.assertTrue(all(_font(out['visual_font_size']).getlength(line)<=available for line in out['display_lines']))
        self.assertTrue(covers(out['mask_rect'],b['bounds']));self.assertTrue(covers(out['mask_rect'],out['body_rect']))
        self.assertEqual(out['text'],b['text'])

    def test_jitter_2_to_5_source_pixels_never_moves_mask_or_body(self):
        for size in ((960,540),(1920,1080)):
            layout=VisualLayout();b=block(source_size=size);first=layout.arrange([b],self.style,'s')[0]
            for dx,dy in ((2,2),(-2,-2),(5,-5),(-5,5),(0,0)):
                moved=deepcopy(b);moved['bounds']=[b['bounds'][i]+(dx/size[0] if i%2==0 else dy/size[1]) for i in range(4)]
                out=layout.arrange([moved],self.style,'s')[0]
                for key in ('mask_rect','body_rect','name_rect','display_lines','visual_font_size'):self.assertEqual(out[key],first[key])
                self.assertTrue(covers(out['mask_rect'],moved['bounds']))

    def test_larger_box_drift_expands_coverage_without_moving_text(self):
        b=block();first=self.arrange(b)[0];moved=deepcopy(b);moved['bounds']=[.4,.76,.6,.81]
        out=self.arrange(moved)[0]
        self.assertEqual(out['body_rect'],first['body_rect']);self.assertTrue(covers(out['mask_rect'],moved['bounds']))
        self.assertTrue(covers(out['mask_rect'],first['mask_rect']))

    def test_name_appearance_and_disappearance_does_not_move_body(self):
        b=block(speaker='');first=self.arrange(b)[0];b['speaker']='Scout';named=self.arrange(b)[0]
        self.assertEqual(named['body_rect'],first['body_rect']);self.assertTrue(named['name_lines'])
        b['speaker']='';out=self.arrange(b)[0]
        self.assertEqual(out['body_rect'],first['body_rect']);self.assertFalse(out['name_lines'])
        self.assertEqual(out['mask_rect'],named['mask_rect'])

    def test_new_source_A_B_A_gets_new_anchor_each_time(self):
        a=self.arrange(block('A',bounds=[.2,.5,.4,.55],job=1))[0]
        b=self.arrange(block('B',bounds=[.5,.8,.7,.85],job=2))[0]
        again=self.arrange(block('A',bounds=[.5,.8,.7,.85],job=3))[0]
        self.assertNotEqual(a['body_rect'],again['body_rect']);self.assertEqual(b['body_rect'][3],again['body_rect'][3])
        self.assertEqual(len(self.layout.locks),1)

    def test_session_change_and_empty_state_clear_position_locks(self):
        b=block();self.arrange(b);b['bounds']=[.4,.7,.6,.75]
        old=self.arrange(b)[0];new=self.arrange(b,generation='next')[0]
        self.assertNotEqual(old['body_rect'],new['body_rect'])
        self.arrange(generation='next');self.assertFalse(self.layout.locks)

    def test_invalid_or_missing_box_uses_saved_fallback(self):
        for bounds in (None,[-.1,.8,.4,.9],[.5,.8,.4,.9],[float('nan'),.8,.7,.9],[0,0,1,1]):
            b=block();b['bounds']=bounds;out=self.arrange(b)[0]
            for x,y in zip(out['mask_rect'],self.style['mask_rect']):self.assertAlmostEqual(x,y)

    def test_fixed_mode_keeps_original_geometry_and_renderer_path(self):
        self.style['position']='fixed';out=self.arrange(block('Kısa.',bounds=[.4,.2,.6,.3]))[0]
        for x,y in zip(out['mask_rect'],self.style['mask_rect']):self.assertAlmostEqual(x,y)
        self.assertNotIn('body_rect',out)

    def test_absent_font_metrics_preserve_legacy_fallback(self):
        with patch('ediz_game_translator.subtitles.layout._font',return_value=None):
            out=self.arrange(block())[0]
        self.assertNotIn('body_rect',out)
        self.assertGreaterEqual(out['mask_rect'][2]-out['mask_rect'][0],.78-1e-9)

    def test_three_overlapping_sources_are_readable_and_cover_all_english(self):
        rows=[block('Uzun bir Türkçe cümle. '*15,speaker='Scout' if i!=1 else '',job=i+1,bounds=[.25,.7+i*.04,.75,.75+i*.04]) for i in range(3)]
        out=self.arrange(*rows);self.assertEqual(len(out),3)
        for b,row in zip(out,rows):
            self.assertTrue(covers(b['mask_rect'],row['bounds']));self.assertTrue(covers(b['mask_rect'],b['body_rect']))
        bodies=sorted(b['body_rect'] for b in out)
        self.assertTrue(all(a[3]<=b[1]+1e-8 for a,b in zip(bodies,bodies[1:])))

    def test_three_unknown_boxes_keep_separate_text_slots(self):
        rows=[dict(block('Replik '+str(i),job=i+1),bounds=None) for i in range(3)]
        out=self.arrange(*rows);bodies=sorted(b['body_rect'] for b in out)
        self.assertTrue(all(a[3]<=b[1]+1e-8 for a,b in zip(bodies,bodies[1:])))

    def test_mask_and_source_coverage_match_1080p_720p_and_letterbox(self):
        b=block();out=self.arrange(b)[0]
        for width,height in ((1920,1080),(1280,720),(960,540),(1280,1024)):
            self.assertTrue(covers(viewport_rect(out['mask_rect'],width,height,b['source_size']),viewport_rect(b['bounds'],width,height,b['source_size'])))

    def test_unbroken_word_is_wrapped_without_losing_characters(self):
        word='Çğıöşü'*45;out=self.arrange(block(word))[0]
        self.assertEqual(''.join(out['display_lines']),word)
        self.assertGreater(len(out['display_lines']),1)

    def test_nearby_new_job_can_reuse_geometry_without_reusing_any_text_or_mask(self):
        now=[10.];layout=VisualLayout(clock=lambda:now[0]);a=block('İlk replik.',job=1)
        first=layout.arrange([a],self.style,'s')[0]
        now[0]=10.05;self.assertEqual(layout.arrange([],self.style,'s'),[])
        now[0]=10.15;b=block('İlk replik.',job=2,bounds=[.4+3/960,.8-3/540,.6+3/960,.85-3/540])
        second=layout.arrange([b],self.style,'s')[0]
        self.assertEqual(second['id'],2);self.assertEqual(second['body_rect'],first['body_rect'])
        self.assertEqual(second['mask_rect'],first['mask_rect']);self.assertTrue(covers(second['mask_rect'],b['bounds']))
        now[0]=10.2;b=block('Farklı ve güncel B.',job=3,bounds=b['bounds'])
        result=layout.arrange([b],self.style,'s')[0];self.assertEqual(result['text'],'Farklı ve güncel B.')

    def test_recent_geometry_expires_and_never_crosses_session(self):
        now=[10.];layout=VisualLayout(clock=lambda:now[0]);a=block();first=layout.arrange([a],self.style,'s')[0]
        now[0]=10.4;b=block(job=2,bounds=[.4,.8+3/540,.6,.85+3/540])
        after=layout.arrange([b],self.style,'s')[0];self.assertNotEqual(after['body_rect'],first['body_rect'])
        now[0]=10.45;a['id']=a['subtitle_id']=3
        new=layout.arrange([a],self.style,'new-session')[0]
        self.assertEqual(new['body_rect'],first['body_rect']);self.assertEqual(len(layout.recent),1)


class NativeVisualTests(unittest.TestCase):
    def test_canvas_glyph_bounds_fit_mask_for_short_long_and_three_sources(self):
        import tkinter as tk
        from ediz_game_translator.subtitles.canvas_view import draw_captions
        root=tk.Tk();root.withdraw();canvas=tk.Canvas(root)
        try:
            for size in ((1920,1080),(1280,720),(960,540),(1280,1024)):
                for rows in ([block('Git!')],[block('Türkçe uzun bir altyazı. '*15)],[block('Konuşma. '*18,job=i+1,bounds=[.2,.6+i*.08,.8,.65+i*.08]) for i in range(3)]):
                    out=arrange_blocks(rows,DEFAULT_STYLE);draw_captions(canvas,out,DEFAULT_STYLE,*size)
                    masks=[canvas.coords(item) for item in canvas.find_withtag('mask')]
                    for tag in ('speaker','dialogue'):
                        for item in canvas.find_withtag(tag):
                            rect=canvas.bbox(item)
                            self.assertTrue(any(covers(mask,rect) for mask in masks),(size,tag,rect,masks))
        finally:root.destroy()

    def test_native_does_not_repaint_for_raw_ocr_box_jitter(self):
        from unittest.mock import MagicMock
        from ediz_game_translator.subtitles.desktop_overlay import DesktopOverlay
        overlay=DesktopOverlay.__new__(DesktopOverlay);overlay.enabled=True;overlay._previous=None
        overlay.width=1920;overlay.height=1080;overlay.font=36;overlay.canvas=MagicMock()
        rows=arrange_blocks([block()],DEFAULT_STYLE)
        with patch('ediz_game_translator.subtitles.canvas_view.draw_captions') as draw:
            overlay.render_blocks(rows,DEFAULT_STYLE);rows[0]['bounds'][1]+=.001
            overlay.render_blocks(rows,DEFAULT_STYLE);self.assertEqual(draw.call_count,1)
            overlay.render_blocks([],DEFAULT_STYLE);self.assertEqual(draw.call_count,2)
