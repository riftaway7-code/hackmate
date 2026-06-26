import os
import sys
from pathlib import Path

from updater import check_and_update
check_and_update()

src = Path(__file__).parent.parent / "src" / "hackmate.py"
if not src.exists():
    print("Migration failed. Please re-clone:")
    print("  git clone https://github.com/riftaway7-code/hackmate.git")
    print("  cd hackmate/src && sudo python3 hackmate.py")
    sys.exit(1)

os.execv(sys.executable, [sys.executable, str(src)])
