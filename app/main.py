"""Application entry point for the desktop UI and package smoke checks."""

from __future__ import annotations

import argparse
import sys

from app.diagnostics.bundle import validate_installation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Motion Analysis Studio")
    parser.add_argument("--smoke-test", action="store_true", help="validate runtime capabilities without opening the UI")
    arguments = parser.parse_args(argv)
    if arguments.smoke_test:
        issues = validate_installation(include_external=False)
        if issues:
            for issue in issues:
                print(issue, file=sys.stderr)
            return 1
        print("Motion Analysis Studio smoke test: OK")
        return 0

    from PySide6.QtWidgets import QApplication

    qt_args = [sys.argv[0], *(argv if argv is not None else sys.argv[1:])]
    application = QApplication(qt_args)
    from app.gui.main_window import MainWindow

    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
