from __future__ import annotations

from pages.base_page import BasePage
from pages.locators.playwright_docs import PlaywrightDocsLocators as L


class PlaywrightLandingPage(BasePage):
    """Example page object for the public Playwright documentation site."""

    INTRO_PATH = "/docs/intro"

    def open_home(self) -> None:
        self.step("Open Playwright home")
        self.page.goto("/", wait_until=self.settings.navigation_wait_until)  # type: ignore[arg-type]

    def open_docs_intro(self) -> None:
        self.goto_path(self.INTRO_PATH)

    def expect_installation_heading(self) -> None:
        role, name = L.HEADING_INSTALLATION
        self.expect_heading(name)
