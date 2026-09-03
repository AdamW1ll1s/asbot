from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading

from .config import load_config
from .hotkeys import GlobalHotkeys
from .runner import AutomationRunner
from .ui import run_ui
from .windows import WindowsOnlyError


def main() -> int:
    parser = argparse.ArgumentParser(description="Authorized visual automation starter for Windows")
    parser.add_argument("--config", default="config/profile.yaml", help="Path to YAML profile")
    parser.add_argument("--cli", action="store_true", help="Run the original terminal-only controller")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.cli:
        try:
            return run_ui(args.config)
        except (OSError, ValueError, WindowsOnlyError) as error:
            logging.error("Startup failed: %s", error)
            return 2
    try:
        config = load_config(args.config)
        runner = AutomationRunner(config)
        hotkeys = GlobalHotkeys({config.toggle_hotkey: runner.toggle, config.emergency_stop_hotkey: runner.stop})
    except (OSError, ValueError, WindowsOnlyError) as error:
        logging.error("Startup failed: %s", error)
        return 2

    shutdown = threading.Event()

    def stop(_: int, __: object) -> None:
        runner.stop()
        hotkeys.stop()
        shutdown.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    hotkeys.start()
    logging.info("Ready. %s toggles; %s immediately stops.", config.toggle_hotkey, config.emergency_stop_hotkey)
    try:
        shutdown.wait()
    finally:
        runner.stop()
        hotkeys.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
