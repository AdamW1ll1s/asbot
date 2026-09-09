"""Entry point used by standalone Windows builds."""

import os
from pathlib import Path
import sys

from game_assist.main import main


if __name__ == "__main__":
    # Resolve config/, logs/ and debug/ next to the launcher/executable even
    # when a shortcut or terminal starts it with another working directory.
    os.chdir(Path(sys.argv[0]).resolve().parent)
    raise SystemExit(main())
