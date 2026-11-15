from bootstrap import configure_paths
configure_paths()
import unittest
from PIL import Image,ImageDraw
from ediz_game_translator.capture.image_change import ImageChangeGate


def frame(text=''):
    im=Image.new('RGB',(960,160),'black')
    if text:ImageDraw.Draw(im).text((300,80),text,fill='white',font_size=30)
    return im


class ImageChangeTests(unittest.TestCase):
    def test_stable_image_skips_and_mandatory_periodic_rescan(self):
        g=ImageChangeGate();im=frame('Stay here.')
        self.assertTrue(g.should_ocr(im,0)[0])
        self.assertFalse(g.should_ocr(im,.04)[0])
        self.assertEqual(g.should_ocr(im,.16)[1],'periodic')

    def test_changed_short_words_and_blank_trigger_immediately(self):
        g=ImageChangeGate()
        for i,text in enumerate(('Go!','No!','Oh!','Hi!','')):
            run,reason,_=g.should_ocr(frame(text),i*.02)
            self.assertTrue(run,(text,reason))

    def test_low_confidence_recheck_does_not_wait_for_full_interval(self):
        g=ImageChangeGate();im=frame('Wait here.')
        g.should_ocr(im,0);g.confirm=True
        self.assertEqual(g.should_ocr(im,.06)[1],'confirmation')

    def test_subthreshold_change_is_eventually_rescanned(self):
        g=ImageChangeGate();im=frame()
        g.should_ocr(im,0);im.putpixel((20,20),(255,255,255))
        self.assertFalse(g.should_ocr(im,.02)[0])
        self.assertTrue(g.should_ocr(im,.16)[0])
