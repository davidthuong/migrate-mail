#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diem vao cua Postboat. Chay: ./postboat.py <lenh>  hoac  python3 postboat.py <lenh>"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from postboat.cli import main

if __name__ == "__main__":
    sys.exit(main())
