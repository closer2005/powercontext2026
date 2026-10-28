"""支持 ``python -m speckit`` 直接调用 CLI。"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())