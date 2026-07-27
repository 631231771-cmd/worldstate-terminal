"""Native desktop window for World State Terminal."""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
START_SCRIPT = REPO_ROOT / "scripts" / "worldstate.ps1"
APP_URL = "http://127.0.0.1:4173/?lang=zh&desktop=1"
FRONTEND_PROBE = "http://127.0.0.1:4173/?lang=zh"
ENGINE_PROBE = "http://127.0.0.1:8000/v1/health"
ICON_PATH = REPO_ROOT / "src-tauri" / "icons" / "icon.ico"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def endpoint_ready(url: str, timeout: float = 1.5) -> bool:
    """Return whether a local endpoint is responding."""

    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            return 200 <= response.status < 500
    except (OSError, urllib.error.URLError, ValueError):
        return False


def services_ready() -> bool:
    return endpoint_ready(FRONTEND_PROBE) and endpoint_ready(ENGINE_PROBE)


def powershell_command(command: str) -> list[str]:
    executable = "powershell.exe" if os.name == "nt" else "pwsh"
    arguments = [
        executable,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(START_SCRIPT),
        command,
    ]
    if command in {"start", "restart"}:
        arguments.append("-NoBrowser")
    return arguments


def run_service_command(
    command: str, timeout: int = 360
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        powershell_command(command),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )


def ensure_webengine() -> bool:
    """Install the isolated Qt desktop runtime once when it is missing."""

    if importlib.util.find_spec("PySide6.QtWebEngineWidgets") is not None:
        try:
            import PySide6.QtWebEngineWidgets  # noqa: F401, PLC0415
        except ImportError:
            return False
        return True
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--user",
            "PySide6>=6.10,<6.12",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
        creationflags=CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        return False
    try:
        import PySide6.QtWebEngineWidgets  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


def check_runtime() -> int:
    webengine_available = ensure_webengine()
    checks = {
        "repository": REPO_ROOT.exists(),
        "launcher": START_SCRIPT.exists(),
        "qt": importlib.util.find_spec("PySide6.QtWidgets") is not None,
        "webengine": webengine_available,
    }
    for name, available in checks.items():
        print(f"{name}: {'ok' if available else 'missing'}")
    return 0 if all(checks.values()) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="World State Terminal desktop app")
    parser.add_argument(
        "--check", action="store_true", help="check the desktop runtime"
    )
    args = parser.parse_args()
    if args.check:
        return check_runtime()
    if not ensure_webengine():
        from tkinter import Tk, messagebox

        root = Tk()
        root.withdraw()
        messagebox.showerror(
            "世界状态终端",
            "桌面组件准备失败。\n\n请确认电脑可以联网，然后再次双击“世界状态终端 App”。",
        )
        root.destroy()
        return 1

    from PySide6.QtCore import QThread, QUrl, Signal
    from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QShortcut
    from PySide6.QtWebEngineCore import QWebEnginePage
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import (
        QApplication,
        QLabel,
        QMainWindow,
        QMessageBox,
        QVBoxLayout,
        QWidget,
    )

    class StartupWorker(QThread):
        ready = Signal(bool)
        failed = Signal(str)

        def run(self) -> None:
            already_running = services_ready()
            if not already_running:
                try:
                    result = run_service_command("start")
                except (OSError, subprocess.SubprocessError) as error:
                    self.failed.emit(str(error))
                    return
                if result.returncode != 0:
                    details = (result.stderr or result.stdout or "未知启动错误").strip()
                    self.failed.emit(details[-1800:])
                    return
            if not services_ready():
                self.failed.emit("本地服务已经启动，但终端页面没有在预期时间内响应。")
                return
            self.ready.emit(not already_running)

    class TerminalPage(QWebEnginePage):
        def acceptNavigationRequest(
            self,
            url: QUrl,
            navigation_type: QWebEnginePage.NavigationType,
            is_main_frame: bool,
        ) -> bool:
            if (
                is_main_frame
                and navigation_type
                == QWebEnginePage.NavigationType.NavigationTypeLinkClicked
                and url.host() not in {"127.0.0.1", "localhost"}
            ):
                QDesktopServices.openUrl(url)
                return False
            return super().acceptNavigationRequest(url, navigation_type, is_main_frame)

    class TerminalWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.owns_services = False
            self.worker: StartupWorker | None = None
            self.view: QWebEngineView | None = None
            self.zoom_factor = 1.0
            self.setWindowTitle("世界状态终端 · World State Terminal")
            self.resize(1500, 940)
            self.setMinimumSize(1080, 700)
            if ICON_PATH.exists():
                self.setWindowIcon(QIcon(str(ICON_PATH)))
            self._show_startup()
            self._bind_shortcuts()
            self._start()

        def _show_startup(self) -> None:
            container = QWidget()
            layout = QVBoxLayout(container)
            layout.setContentsMargins(48, 48, 48, 48)
            label = QLabel(
                "正在连接今天的世界…\n\n首次打开可能需要一点时间来准备数据。"
            )
            label.setStyleSheet(
                "color: #e8eef7; font-size: 22px; font-weight: 600; line-height: 1.6;"
            )
            label.setWordWrap(True)
            layout.addStretch(1)
            layout.addWidget(label)
            layout.addStretch(1)
            container.setStyleSheet("background: #080c12;")
            self.setCentralWidget(container)

        def _start(self) -> None:
            self.worker = StartupWorker(self)
            self.worker.ready.connect(self._load_terminal)
            self.worker.failed.connect(self._show_error)
            self.worker.start()

        def _load_terminal(self, owns_services: bool) -> None:
            self.owns_services = owns_services
            view = QWebEngineView(self)
            view.setPage(TerminalPage(view))
            view.setZoomFactor(self.zoom_factor)
            view.setUrl(QUrl(APP_URL))
            self.view = view
            self.setCentralWidget(view)

        def _show_error(self, details: str) -> None:
            QMessageBox.critical(
                self,
                "世界状态终端无法启动",
                "启动没有完成。\n\n"
                f"{details}\n\n"
                "详细记录保存在项目的 .runtime\\logs 文件夹中。",
            )

        def _bind_shortcuts(self) -> None:
            QShortcut(
                QKeySequence.StandardKey.ZoomIn, self, activated=lambda: self._zoom(0.1)
            )
            QShortcut(
                QKeySequence.StandardKey.ZoomOut,
                self,
                activated=lambda: self._zoom(-0.1),
            )
            QShortcut(QKeySequence("Ctrl+0"), self, activated=self._reset_zoom)
            QShortcut(QKeySequence("F5"), self, activated=self._reload)

        def _zoom(self, delta: float) -> None:
            self.zoom_factor = min(1.5, max(0.8, self.zoom_factor + delta))
            if self.view is not None:
                self.view.setZoomFactor(self.zoom_factor)

        def _reset_zoom(self) -> None:
            self.zoom_factor = 1.0
            if self.view is not None:
                self.view.setZoomFactor(self.zoom_factor)

        def _reload(self) -> None:
            if self.view is not None:
                self.view.reload()

        def closeEvent(self, event: object) -> None:  # noqa: N802
            if self.owns_services:
                subprocess.Popen(
                    powershell_command("stop"),
                    cwd=REPO_ROOT,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW,
                )
            super().closeEvent(event)

    app = QApplication(sys.argv)
    app.setApplicationName("世界状态终端")
    app.setOrganizationName("World State Terminal")
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    window = TerminalWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
