#!/usr/bin/env python
"""CLI wrapper: run the full arXiv Daily Paper pipeline."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from commands.daily import main

main()
