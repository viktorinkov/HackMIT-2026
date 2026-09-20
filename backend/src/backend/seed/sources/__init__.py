"""Seed sources are discovered automatically: drop a module with a Source
subclass into this package and `peel-seed` picks it up."""

from __future__ import annotations

import importlib
import pkgutil

from backend.seed.base import DEFAULT_ORDER, Source


def discover() -> dict[str, type[Source]]:
    found: dict[str, type[Source]] = {}
    for module_info in pkgutil.iter_modules(__path__):
        module = importlib.import_module(f"{__name__}.{module_info.name}")
        for value in vars(module).values():
            if isinstance(value, type) and issubclass(value, Source) and value is not Source:
                if getattr(value, "name", None):
                    found[value.name] = value
    ordered = {name: found[name] for name in DEFAULT_ORDER if name in found}
    ordered.update({name: cls for name, cls in sorted(found.items()) if name not in ordered})
    return ordered
