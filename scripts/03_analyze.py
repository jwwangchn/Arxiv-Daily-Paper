#!/usr/bin/env python
"""CLI wrapper: analyze arXiv papers with DeepSeek."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from commands.analyze import main

main()
