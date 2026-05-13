#!/usr/bin/env python
"""CLI wrapper: build the static GitHub Pages site."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from commands.build import main

main()
