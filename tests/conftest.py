from __future__ import annotations

import pytest
from playwright.sync_api import Page

from pages.playwright_landing_page import PlaywrightLandingPage
from ui_automation.config import Settings


@pytest.fixture
def landing_page(
    page: Page,
    settings: Settings,
    request: pytest.FixtureRequest,
    test_artifacts_dir,
) -> PlaywrightLandingPage:
    return PlaywrightLandingPage(page, settings, request, test_artifacts_dir)
