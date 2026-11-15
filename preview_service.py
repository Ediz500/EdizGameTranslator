"""Read-only shared OCR callable; a preview never owns a second camera."""
import threading


class SharedOCR:
    def __init__(self,factory):
        self.factory=factory
        self.engine=None
        self.lock=threading.Lock()

    def __call__(self,image):
        with self.lock:
            if self.engine is None:self.engine=self.factory()
            return self.engine(image)
