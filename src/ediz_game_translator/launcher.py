"""Windowed entry point; error metadata only, never exception messages/secrets."""
import argparse
import logging
from pathlib import Path
import sys
import threading
import traceback


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--real-camera',action='store_true')
    parser.add_argument('--report',default='PACKAGE_CHECK.json')
    parser.add_argument('--overlay-image')
    parser.add_argument('--local-python')
    parser.add_argument('--local-model')
    parser.add_argument('--local-device',choices=['cpu','cuda'],default='cpu')
    args=parser.parse_args()
    from ediz_game_translator.core import config_folder
    folder=Path(args.report).resolve().parent if args.self_test else config_folder()/'logs'
    folder.mkdir(parents=True,exist_ok=True)
    logpath=folder/('package_check.log' if args.self_test else 'startup.log')
    # noconsole executables have no stdout/stderr. Local OCR libraries expect them.
    stream=logpath.open('a',encoding='utf-8')
    if sys.stdout is None:sys.stdout=stream
    if sys.stderr is None:sys.stderr=stream
    logging.basicConfig(filename=logpath,level=logging.WARNING,encoding='utf-8')
    def report_error(kind,value,tb):
        frames='; '.join(f'{Path(f.filename).name}:{f.lineno}' for f in traceback.extract_tb(tb))
        logging.error('%s at %s',kind.__name__,frames)
        import tkinter.messagebox as box
        box.showerror('Ediz Game Translator','Uygulama bir sorunla karşılaştı. Hata türü: '+kind.__name__+'\nYerel günlük: '+str(logpath))
    sys.excepthook=report_error
    threading.excepthook=lambda a:logging.error('Worker error: %s',a.exc_type.__name__)
    try:
        if args.self_test:
            from ediz_game_translator.diagnostics.package_checks import run
            run(args)
        else:
            import tkinter as tk
            from ediz_game_translator import app
            tk.Tk.report_callback_exception=lambda self,*error:report_error(*error)
            app.main()
    except Exception:
        if args.self_test:
            from ediz_game_translator.core import atomic_json
            atomic_json(Path(args.report),dict(ok=False,error=sys.exc_info()[0].__name__,cloud_sdk_loaded=False))
            raise
        report_error(*sys.exc_info())
    finally:stream.close()


if __name__=='__main__':main()
