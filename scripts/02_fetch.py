#!/usr/bin/env python
"""CLI wrapper: fetch daily arXiv metadata."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from commands.fetch import main

main()
