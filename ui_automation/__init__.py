"""Web UI test runner package (CLI entry: python -m ui_automation)."""

__version__ = "1.0.0"
__all__ = ["__version__", "load_settings", "Settings"]

from ui_automation.config import Settings, load_settings
