"""ViGEmBus driver detection and install-link helpers."""
from dataclasses import dataclass
import os
import subprocess
import webbrowser


VIGEMBUS_INSTALL_URL = "https://github.com/nefarius/ViGEmBus/releases/latest"
VIGEMBUS_DOCS_URL = "https://docs.nefarius.at/projects/ViGEm/How-to-Install/"


@dataclass(frozen=True)
class DriverStatus:
    installed: bool
    running: bool
    message: str
    detail: str

    @property
    def ok(self):
        return self.installed and self.running


def check_vigembus():
    if os.name != "nt":
        return DriverStatus(
            installed=False,
            running=False,
            message="虚拟手柄驱动只支持 Windows。",
            detail="This helper requires ViGEmBus on Windows.",
        )

    try:
        result = subprocess.run(
            ["sc.exe", "query", "ViGEmBus"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        return DriverStatus(
            installed=False,
            running=False,
            message="无法检查虚拟手柄驱动；点右侧按钮查看安装页。",
            detail=str(exc),
        )

    detail = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    normalized = detail.upper()
    missing = result.returncode != 0 and (
        "1060" in normalized
        or "DOES NOT EXIST" in normalized
        or "不存在" in detail
        or "找不到" in detail
    )
    installed = not missing and ("VIGEMBUS" in normalized or "STATE" in normalized or result.returncode == 0)
    running = installed and ("RUNNING" in normalized or "正在运行" in detail or "4  RUNNING" in normalized)

    if running:
        return DriverStatus(
            installed=True,
            running=True,
            message="虚拟手柄驱动已就绪。",
            detail=detail,
        )
    if installed:
        return DriverStatus(
            installed=True,
            running=False,
            message="已检测到 ViGEmBus，但服务未运行；建议重启电脑或重新安装驱动。",
            detail=detail,
        )
    return DriverStatus(
        installed=False,
        running=False,
        message="未检测到虚拟手柄驱动；首次使用请先安装 ViGEmBus。",
        detail=detail,
    )


def open_vigembus_download():
    webbrowser.open(VIGEMBUS_INSTALL_URL)
