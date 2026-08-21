"""GitHub Release 自动更新。

更新检查只读取公开 GitHub Release 元数据，不参与点名、Excel 或 SQLite
任务；下载完成后先做 SHA-256 校验，再由独立 cmd 进程等待当前 EXE 退出并
替换文件。运行数据始终位于 EXE 同级目录，不会随更新包覆盖。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QThread, Signal

from version import __version__

REPOSITORY = "HX-Wrdzgzs/ham-checkin-assistant"
LATEST_API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
FALLBACK_MANIFEST_URL = (
    "https://raw.githubusercontent.com/"
    f"{REPOSITORY}/codex/ham-checkin-release/updates/latest.json"
)
UPDATE_ASSET_NAME = "HAM点名助手.exe"
CHECKSUM_ASSET_NAME = "SHA256SUMS.txt"
MAX_UPDATE_BYTES = 250 * 1024 * 1024
_VERSION_RE = re.compile(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)")


class UpdateError(RuntimeError):
    """更新检查、下载或校验失败。"""


@dataclass(frozen=True)
class ReleaseInfo:
    """可安装的 GitHub Release 信息。"""

    version: str
    tag_name: str
    html_url: str
    download_url: str
    expected_sha256: str | None


def version_key(value: str) -> tuple[int, int, int]:
    """把 v0.9.2 / 0.9.2 统一为可比较的版本三元组。"""
    match = _VERSION_RE.search(str(value or ""))
    if match is None:
        raise UpdateError(f"无法识别版本号：{value!r}")
    return tuple(int(part) for part in match.groups())


def _allowed_release_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    return (
        parsed.scheme.lower() == "https"
        and parsed.netloc.lower() == "github.com"
        and parsed.path.lower().startswith(
            f"/{REPOSITORY.lower()}/releases/download/"
        )
    )


def _read_url(
    url: str,
    *,
    timeout: float,
    accept: str,
    opener=None,
) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": f"ham-checkin-assistant/{__version__}",
        },
    )
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=timeout) as response:
            return response.read()
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        raise UpdateError(f"访问更新服务失败：{exc}") from exc


def _asset_url(assets: list[dict], name: str) -> str | None:
    for asset in assets:
        # GitHub 对非 ASCII 上传文件名可能把 API name 归一化为 HAM.exe，
        # 但会保留 Release 页面上的 label；两者都属于同一个受信任资产。
        if (str(asset.get("name") or "") == name
                or str(asset.get("label") or "") == name):
            url = str(asset.get("browser_download_url") or "")
            return url if _allowed_release_url(url) else None
    return None


def _checksum_for(text: str, asset_name: str) -> str | None:
    """解析 sha256sum 常见格式：<hash>  <filename> / <hash> *<filename>。"""
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        digest, filename = parts
        if (filename.lstrip("*").strip() == asset_name
                and re.fullmatch(r"[0-9a-fA-F]{64}", digest)):
            return digest.lower()
    return None


def check_latest_release(
    current_version: str = __version__,
    *,
    timeout: float = 5.0,
    opener=None,
) -> ReleaseInfo | None:
    """查询最新稳定 Release；没有更新时返回 None。"""
    try:
        raw = _read_url(
            LATEST_API_URL,
            timeout=timeout,
            accept="application/vnd.github+json",
            opener=opener,
        )
        return _release_from_api_payload(raw, current_version, timeout=timeout, opener=opener)
    except UpdateError as api_error:
        # GitHub 未认证 API 有公共限流；公开 raw 清单不依赖 API 配额，且下载仍
        # 只允许指向 GitHub Release 资产。两条路径都失败才报告检查失败。
        try:
            manifest_raw = _read_url(
                FALLBACK_MANIFEST_URL,
                timeout=timeout,
                accept="application/json",
                opener=opener,
            )
            return _release_from_manifest(manifest_raw, current_version)
        except UpdateError as manifest_error:
            raise UpdateError(
                f"更新 API 失败：{api_error}；备用清单失败：{manifest_error}"
            ) from api_error


def _release_from_api_payload(
    raw: bytes,
    current_version: str,
    *,
    timeout: float,
    opener=None,
) -> ReleaseInfo | None:
    """解析 GitHub API 的 latest release 响应。"""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("GitHub 更新响应不是有效 JSON") from exc
    if not isinstance(payload, dict):
        raise UpdateError("GitHub 更新响应格式异常")

    tag_name = str(payload.get("tag_name") or "")
    latest_version = version_key(tag_name)
    if latest_version <= version_key(current_version):
        return None

    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("Release 没有有效的附件列表")
    download_url = _asset_url(assets, UPDATE_ASSET_NAME)
    if not download_url:
        raise UpdateError(f"Release 缺少受信任的 {UPDATE_ASSET_NAME} 附件")

    expected_sha256 = None
    checksum_url = _asset_url(assets, CHECKSUM_ASSET_NAME)
    if checksum_url:
        checksum_raw = _read_url(
            checksum_url,
            timeout=timeout,
            accept="application/octet-stream",
            opener=opener,
        )
        expected_sha256 = _checksum_for(
            checksum_raw.decode("utf-8", errors="replace"), UPDATE_ASSET_NAME)

    return ReleaseInfo(
        version=f"{latest_version[0]}.{latest_version[1]}.{latest_version[2]}",
        tag_name=tag_name,
        html_url=str(payload.get("html_url") or ""),
        download_url=download_url,
        expected_sha256=expected_sha256,
    )


def _release_from_manifest(raw: bytes, current_version: str) -> ReleaseInfo | None:
    """解析仓库公开备用清单，下载地址仍必须是 GitHub Release。"""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("备用更新清单不是有效 JSON") from exc
    if not isinstance(payload, dict):
        raise UpdateError("备用更新清单格式异常")

    version = str(payload.get("version") or payload.get("tag_name") or "")
    latest_version = version_key(version)
    if latest_version <= version_key(current_version):
        return None
    download_url = str(payload.get("download_url") or "")
    if not _allowed_release_url(download_url):
        raise UpdateError("备用清单下载地址不是受信任的 GitHub Release 地址")
    expected_sha256 = str(payload.get("sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise UpdateError("备用清单缺少有效 SHA256")
    tag_name = str(payload.get("tag_name") or f"v{latest_version[0]}.{latest_version[1]}.{latest_version[2]}")
    html_url = str(payload.get("html_url") or f"https://github.com/{REPOSITORY}/releases/tag/{tag_name}")
    return ReleaseInfo(
        version=f"{latest_version[0]}.{latest_version[1]}.{latest_version[2]}",
        tag_name=tag_name,
        html_url=html_url,
        download_url=download_url,
        expected_sha256=expected_sha256,
    )


def download_update(
    release: ReleaseInfo,
    *,
    timeout: float = 60.0,
    opener=None,
    should_cancel=None,
) -> Path:
    """下载并校验 Release EXE，返回临时文件路径。"""
    if not release.expected_sha256:
        raise UpdateError("Release 缺少 HAM点名助手.exe 的 SHA256 校验值，已停止自动更新")
    if not _allowed_release_url(release.download_url):
        raise UpdateError("更新下载地址不是受信任的 GitHub Release 地址")

    target = Path(tempfile.gettempdir()) / (
        f"ham-checkin-update-{os.getpid()}-{secrets.token_hex(6)}.exe"
    )
    request = urllib.request.Request(
        release.download_url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": f"ham-checkin-assistant/{__version__}",
        },
    )
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=timeout) as response, target.open("wb") as out:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_UPDATE_BYTES:
                raise UpdateError("更新文件超过安全大小限制")
            total = 0
            while True:
                if should_cancel is not None and should_cancel():
                    raise UpdateError("更新下载已取消")
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPDATE_BYTES:
                    raise UpdateError("更新文件超过安全大小限制")
                out.write(chunk)
        if target.stat().st_size == 0:
            raise UpdateError("下载到的更新文件为空")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest.lower() != release.expected_sha256.lower():
            raise UpdateError("更新文件 SHA256 校验失败，原程序未修改")
        return target
    except (OSError, ValueError, urllib.error.URLError, TimeoutError) as exc:
        target.unlink(missing_ok=True)
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError(f"下载更新失败：{exc}") from exc
    except UpdateError:
        target.unlink(missing_ok=True)
        raise


def can_self_update() -> bool:
    """只有冻结后的 Windows EXE 才能执行替换；源码运行只提供发布页。"""
    return (
        os.name == "nt"
        and bool(getattr(sys, "frozen", False))
        and Path(sys.executable).suffix.lower() == ".exe"
    )


_UPDATE_CMD = r"""@echo off
setlocal EnableExtensions
set "SRC=%~1"
set "DST=%~2"
set "PID=%~3"
:wait_for_app
tasklist /FI "PID eq %PID%" 2>nul | findstr /R /C:" %PID% " >nul
if not errorlevel 1 (
  timeout /t 1 /nobreak >nul
  goto wait_for_app
)
copy /Y "%SRC%" "%DST%.new" >nul
if errorlevel 1 (
  timeout /t 1 /nobreak >nul
  goto wait_for_app
)
move /Y "%DST%.new" "%DST%" >nul
if errorlevel 1 (
  timeout /t 1 /nobreak >nul
  goto wait_for_app
)
start "" "%DST%"
del /Q "%SRC%" >nul 2>&1
del /Q "%~f0" >nul 2>&1
"""


def schedule_self_update(downloaded: Path, target: Path | None = None) -> Path:
    """启动等待脚本，在当前程序退出后替换并重新启动 EXE。"""
    if not can_self_update():
        raise UpdateError("当前是源码运行，不能执行 EXE 自替换")
    downloaded = Path(downloaded).resolve()
    target = Path(target or sys.executable).resolve()
    if not downloaded.is_file() or downloaded == target:
        raise UpdateError("更新临时文件不存在或目标无效")

    script = Path(tempfile.gettempdir()) / (
        f"ham-checkin-update-{os.getpid()}-{secrets.token_hex(6)}.cmd"
    )
    script.write_text(_UPDATE_CMD, encoding="ascii")
    command = [
        os.environ.get("ComSpec", "cmd.exe"),
        "/d",
        "/c",
        str(script),
        str(downloaded),
        str(target),
        str(os.getpid()),
    ]
    try:
        subprocess.Popen(
            command,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )
    except OSError as exc:
        script.unlink(missing_ok=True)
        raise UpdateError(f"无法启动更新替换程序：{exc}") from exc
    return script


class UpdateWorker(QThread):
    """在后台执行一次更新检查或下载，避免启动时阻塞 UI。"""

    result = Signal(object)

    def __init__(self, action: str = "check", release: ReleaseInfo | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.action = action
        self.release = release

    def run(self) -> None:
        try:
            if self.action == "check":
                release = check_latest_release(opener=None)
                self.result.emit({"action": self.action, "release": release})
            elif self.action == "download" and self.release is not None:
                downloaded = download_update(
                    self.release,
                    should_cancel=self.isInterruptionRequested,
                )
                self.result.emit({"action": self.action, "downloaded": downloaded})
            else:
                raise UpdateError("未知的更新任务")
        except Exception as exc:  # noqa: BLE001
            self.result.emit({"action": self.action, "error": str(exc)})
