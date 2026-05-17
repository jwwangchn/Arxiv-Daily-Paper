"""Re-export config from scripts/utils.py for lib package use."""

from utils import PROJECT_ROOT, setup_logging

__all__ = ["PROJECT_ROOT", "setup_logging"]
