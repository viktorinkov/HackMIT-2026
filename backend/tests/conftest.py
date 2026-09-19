import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("PEEL_LIVE") == "1":
        return
    skip_live = pytest.mark.skip(reason="live cluster test; set PEEL_LIVE=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
