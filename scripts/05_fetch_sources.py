#!/usr/bin/env python
"""CLI wrapper: batch fetch conference papers from sources."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from batch.fetch_sources import main

main()
