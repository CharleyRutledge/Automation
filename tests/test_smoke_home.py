from __future__ import annotations

import pytest

from pages.locators.playwright_docs import PlaywrightDocsLocators as L
from pages.playwright_landing_page import PlaywrightLandingPage


@pytest.mark.smoke
def test_home_page_loads(landing_page: PlaywrightLandingPage) -> None:
    landing_page.open_home()
    landing_page.expect_title_contains(L.TITLE_PATTERN)
