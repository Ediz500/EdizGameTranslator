"""Source entry point; keeps BASLAT.bat compatible."""
from pathlib import Path
import sys

source=Path(__file__).resolve().parent/'src'
if str(source) not in sys.path:sys.path.insert(0,str(source))
from ediz_game_translator.launcher import main

if __name__=='__main__':main()
