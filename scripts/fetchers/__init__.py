"""Source fetchers — base classes and registry only."""
from fetchers.base import FetchRequest, FetchResult, make_paper_id, normalize_unified_paper
from fetchers.registry import available_sources, fetch_source, get_fetcher, register

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