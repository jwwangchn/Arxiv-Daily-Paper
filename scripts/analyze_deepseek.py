"""Entry point for DeepSeek analysis — called by GitHub Actions daily pipeline."""
import sys
from pathlib import Path

# Ensure scripts/ directory is on the path
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from commands.analyze import main

if __name__ == "__main__":
    main()
