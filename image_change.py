"""Cheap ROI checks against the last OCR image, with mandatory full rescans."""
import math
import numpy as np
from PIL import Image


class ImageChangeGate:
    def __init__(self,check_interval=.02,full_interval=.15,confirmation_interval=.05,
                 changed_fraction=.0005,pixel_delta=8):
        if not .005<=check_interval<=full_interval<=1:raise ValueError('Invalid scan cadence')
        self.check_interval=check_interval;self.full_interval=full_interval
        self.confirmation_interval=confirmation_interval
        self.changed_fraction=changed_fraction;self.pixel_delta=pixel_delta
        self.reference=None;self.last_ocr=None;self.confirm=False
        self.checks=0;self.ocr_calls=0;self.forced=0;self.skipped=0

    def should_ocr(self,image,now):
        thumb=np.asarray(image.convert('L').resize((192,48),Image.Resampling.BILINEAR),dtype=np.int16)
        self.checks+=1
        fraction=1. if self.reference is None else float(np.mean(np.abs(thumb-self.reference)>=self.pixel_delta))
        due=self.last_ocr is None or now-self.last_ocr>=self.full_interval
        confirmation=self.confirm and (self.last_ocr is None or now-self.last_ocr>=self.confirmation_interval)
        changed=fraction>=self.changed_fraction
        run=changed or due or confirmation
        reason='changed' if changed else 'periodic' if due else 'confirmation' if confirmation else 'unchanged'
        if run:
            self.reference=thumb;self.last_ocr=now;self.ocr_calls+=1
            self.forced+=due and not changed
        else:self.skipped+=1
        return run,reason,fraction

    def summary(self):
        return dict(image_checks=self.checks,ocr_calls=self.ocr_calls,periodic_rescans=self.forced,
                    unchanged_skips=self.skipped)
