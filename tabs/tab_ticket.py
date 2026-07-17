from PySide6.QtWidgets import QVBoxLayout

from lib.base_tab import BaseTab
from lib.db_utils import getResourcePath
from ui_utils import loadUi


class TabTicketPlaceholder(BaseTab):
    def setup(self, tab_index):
        tab = self.tab_widget.widget(tab_index)
        if not tab:
            return
        loaded = loadUi(getResourcePath("layouts/Layout10.ui"))
        if not loaded:
            return
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(loaded.centralWidget())

    def get_tables(self):
        return []

    def get_focus_widget(self):
        return None

    def on_activated(self):
        pass
