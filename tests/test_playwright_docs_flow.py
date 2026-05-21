from __future__ import annotations

from pages.locators.playwright_docs import PlaywrightDocsLocators as L
from pages.playwright_landing_page import PlaywrightLandingPage


def test_playwright_docs_intro_flow(landing_page: PlaywrightLandingPage) -> None:
    landing_page.open_home()
    landing_page.expect_title_contains(L.TITLE_PATTERN)
    landing_page.open_docs_intro()
    landing_page.expect_installation_heading()
