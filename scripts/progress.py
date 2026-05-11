from __future__ import annotations

import os
import sys
from collections.abc import Iterable
from typing import TypeVar

from tqdm import tqdm


T = TypeVar("T")


def is_github_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


def progress_bar(iterable: Iterable[T], *, total: int | None = None, desc: str, unit: str = "it"):
    return tqdm(
        iterable,
        total=total,
        desc=desc,
        unit=unit,
        ascii=is_github_actions(),
        dynamic_ncols=not is_github_actions(),
        mininterval=5.0 if is_github_actions() else 0.5,
        smoothing=0.1,
        file=sys.stderr,
    )
