"""image-editor — entry point."""
from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from config import Config
from widgets.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    config = Config.load()
    win = MainWindow(config)
    win.show()

    exit_code = app.exec()
    config.save()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
