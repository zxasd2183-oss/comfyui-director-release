"""macOS Chrome-style toolbar adapter.

The shared v0.14 Chrome theme expects the Windows updater's
update_manager.button and update_manager.show_dialog interface.
MacUpdater has the equivalent _mac_update_button/show_mac_updates.
This adapter is initialized AFTER setup_updater, before setup_chrome14.
"""
from types import SimpleNamespace
from chrome14 import GlacierChrome14


class MacChrome14(GlacierChrome14):
    def setup_chrome14(self, layout, nav):
        if not hasattr(self, "_mac_update_button"):
            raise RuntimeError("Mac updater must be initialized before the Chrome toolbar")
        if not callable(getattr(self, "show_mac_updates", None)):
            raise RuntimeError("Mac updater dialog callback is missing")
        self.update_manager = SimpleNamespace(
            button=self._mac_update_button,
            show_dialog=self.show_mac_updates,
        )
        super().setup_chrome14(layout, nav)
        self.setWindowTitle("❄ Glacier Browser · macOS v0.14.1")
