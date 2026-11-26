"""Launch the Windows desktop app or its legacy Tkinter view."""
import os
from pathlib import Path
import sys

if __name__ == "__main__":
    if "--legacy" in sys.argv:
        from organizer.legacy.app import main
        main()
    else:
        os.startfile(Path(__file__).resolve().with_name("start.cmd"))
