"""Source fetchers — import to register all fetchers."""
from fetchers.base import FetchRequest, FetchResult, make_paper_id, normalize_unified_paper
from fetchers.registry import available_sources, fetch_source, get_fetcher, register

# Import fetcher implementations to trigger @register
from fetchers import openreview  # noqa: F401
from fetchers import acl_anthology  # noqa: F401
from fetchers import aaai_ojs  # noqa: F401
from fetchers import cvf  # noqa: F401

__all__ = [
    "FetchRequest",
    "FetchResult",
    "make_paper_id",
    "normalize_unified_paper",
    "available_sources",
    "fetch_source",
    "get_fetcher",
    "register",
]
