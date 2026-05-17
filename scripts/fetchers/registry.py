"""Fetcher registry — maps source name to fetcher class."""
from __future__ import annotations

from typing import Callable, Type

from fetchers.base import FetchRequest, FetchResult

_REGISTRY: dict[str, Callable] = {}


def register(name: str) -> Callable:
    """Decorator to register a fetcher class/function."""
    def decorator(cls: Type) -> Type:
        _REGISTRY[name] = cls
        return cls
    return decorator


def get_fetcher(name: str) -> Callable:
    if name not in _REGISTRY:
        raise ValueError(f"Unknown source: {name}. Available: {list(_REGISTRY.keys())}")
    return _REGISTRY[name]


def fetch_source(request: FetchRequest) -> FetchResult:
    """Dispatch to the appropriate fetcher."""
    fetcher_cls = get_fetcher(request.source)
    fetcher = fetcher_cls()
    return fetcher.fetch(request)


def available_sources() -> list[str]:
    return sorted(_REGISTRY.keys())
