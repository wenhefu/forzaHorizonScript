"""File logging and lightweight diagnostics for Forza6Helper."""
import importlib.metadata
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import platform
import subprocess
import sys


APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
LOG_DIR = APP_DIR / "logs"
LOG_PATH = LOG_DIR / "forza6helper.log"


def setup_logging():
    """Create the app logger once per process."""
    LOG_DIR.mkdir(exist_ok=True)

    logger = logging.getLogger("forza6helper")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        handler = RotatingFileHandler(
            LOG_PATH,
            maxBytes=512 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(threadName)s %(name)s: %(message)s"
        ))
        logger.addHandler(handler)

    return logger


def _package_version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def _run_windows_command(args):
    if os.name != "nt":
        return "not windows"
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        return f"failed: {exc}"

    output = (result.stdout or result.stderr or "").strip()
    return f"exit={result.returncode}; {output}"


def log_startup_diagnostics(logger):
    """Write enough environment detail to diagnose controller/driver issues."""
    logger.info("=== Forza6Helper starting ===")
    logger.info("app_dir=%s", APP_DIR)
    logger.info("python_executable=%s", sys.executable)
    logger.info("python_version=%s", sys.version.replace("\n", " "))
    logger.info("platform=%s", platform.platform())
    logger.info("vgamepad_version=%s", _package_version("vgamepad"))
    logger.info("pyinstaller_version=%s", _package_version("pyinstaller"))
    logger.info("ViGEmBus service: %s", _run_windows_command(["sc.exe", "query", "ViGEmBus"]))
