# Explicit library resources only. Never collect project trees or APPDATA.
from PyInstaller.utils.hooks import collect_all,collect_submodules,copy_metadata
from pathlib import Path
root=Path(SPECPATH)
datas=[];binaries=[];hidden=[]
for package in ('rapidocr','onnxruntime','cv2','pygrabber','comtypes','screeninfo','customtkinter'):
    d,b,h=collect_all(package);datas+=d;binaries+=b;hidden+=h
hidden+=['keyring.backends.Windows','win32ctypes.pywin32.win32cred','ediz_game_translator.diagnostics.package_checks']
datas+=copy_metadata('keyring')
datas+=[(str(root/'src/ediz_game_translator/translation/light_translation.py'),'ediz_game_translator/translation')]
a=Analysis([str(root/'launcher.py')],pathex=[str(root/'src')],binaries=binaries,datas=datas,
    hiddenimports=hidden,hookspath=[],hooksconfig={},runtime_hooks=[],
    excludes=['torch','paddle','tensorflow','matplotlib','pytest','IPython','notebook','openai','httpx2','httpcore2','jiter'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='EdizGameTranslator',debug=False,
    bootloader_ignore_signals=False,strip=False,upx=False,console=False)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='EdizGameTranslator')
