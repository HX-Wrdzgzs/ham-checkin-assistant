"""自动更新服务的离线回归测试：不访问真实 GitHub，不启动替换脚本。"""
from __future__ import annotations

import hashlib
import json
import unittest
from unittest import mock

from services.update_service import (
    CHECKSUM_ASSET_NAME,
    UPDATE_ASSET_NAME,
    UpdateError,
    check_latest_release,
    download_update,
    fetch_latest_release,
    version_key,
)


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.headers = {}
        self._read = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size: int = -1) -> bytes:
        if self._read:
            return b""
        self._read = True
        return self.payload


class _Opener:
    def __init__(self, values: dict[str, bytes]) -> None:
        self.values = values
        self.urls: list[str] = []

    def __call__(self, request, timeout: float):
        del timeout
        self.urls.append(request.full_url)
        base_url = request.full_url.split("?", 1)[0]
        return _Response(self.values[base_url])


class _SequenceOpener:
    def __init__(self, payloads: list[bytes]) -> None:
        self.payloads = list(payloads)
        self.urls: list[str] = []

    def __call__(self, request, timeout: float):
        del timeout
        self.urls.append(request.full_url)
        return _Response(self.payloads.pop(0))


def _release_payload(version: str, checksum: str | None) -> tuple[dict, dict[str, bytes]]:
    exe_url = (
        "https://github.com/HX-Wrdzgzs/ham-checkin-assistant/"
        f"releases/download/v{version}/HAM点名助手.exe"
    )
    checksum_url = (
        "https://github.com/HX-Wrdzgzs/ham-checkin-assistant/"
        f"releases/download/v{version}/{CHECKSUM_ASSET_NAME}"
    )
    payload = {
        "tag_name": f"v{version}",
        "html_url": f"https://github.com/HX-Wrdzgzs/ham-checkin-assistant/releases/tag/v{version}",
        "assets": [
            {"name": "HAM.exe", "label": UPDATE_ASSET_NAME,
             "browser_download_url": exe_url},
            {"name": CHECKSUM_ASSET_NAME, "browser_download_url": checksum_url},
        ],
    }
    checksum_text = (
        f"{checksum}  {UPDATE_ASSET_NAME}\n".encode() if checksum else b""
    )
    values = {
        "https://api.github.com/repos/HX-Wrdzgzs/ham-checkin-assistant/releases/latest":
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        checksum_url: checksum_text,
    }
    return payload, values


class TestUpdateService(unittest.TestCase):
    def test_version_key_accepts_release_tag(self):
        self.assertEqual(version_key("v0.9.2"), (0, 9, 2))
        self.assertEqual(version_key("release-12.3.4"), (12, 3, 4))
        with self.assertRaises(UpdateError):
            version_key("latest")

    def test_check_latest_release_accepts_ascii_asset_without_label(self):
        """正式发布固定使用 HAM.exe，不依赖 GitHub 的中文 label 行为。"""
        exe = b"ascii-release-exe"
        digest = hashlib.sha256(exe).hexdigest()
        exe_url = (
            "https://github.com/HX-Wrdzgzs/ham-checkin-assistant/"
            "releases/download/v0.9.4/HAM.exe"
        )
        checksum_url = (
            "https://github.com/HX-Wrdzgzs/ham-checkin-assistant/"
            f"releases/download/v0.9.4/{CHECKSUM_ASSET_NAME}"
        )
        payload = {
            "tag_name": "v0.9.4",
            "html_url": "https://github.com/HX-Wrdzgzs/ham-checkin-assistant/releases/tag/v0.9.4",
            "assets": [
                {"name": "HAM.exe", "browser_download_url": exe_url},
                {"name": CHECKSUM_ASSET_NAME, "browser_download_url": checksum_url},
            ],
        }
        values = {
            "https://api.github.com/repos/HX-Wrdzgzs/ham-checkin-assistant/releases/latest":
                json.dumps(payload).encode("utf-8"),
            checksum_url: f"{digest}  HAM.exe\n".encode(),
        }
        release = check_latest_release("0.9.3", opener=_Opener(values))
        self.assertIsNotNone(release)
        self.assertEqual(release.download_url, exe_url)
        self.assertEqual(release.expected_sha256, digest)

    def test_check_latest_release_reads_checksum(self):
        exe = b"test-exe"
        digest = hashlib.sha256(exe).hexdigest()
        _payload, values = _release_payload("0.9.2", digest)
        release = check_latest_release("0.9.1", opener=_Opener(values))
        self.assertIsNotNone(release)
        self.assertEqual(release.version, "0.9.2")
        self.assertEqual(release.expected_sha256, digest)

    def test_check_latest_release_returns_none_when_current(self):
        _payload, values = _release_payload("0.9.2", "0" * 64)
        self.assertIsNone(check_latest_release("0.9.2", opener=_Opener(values)))

    def test_fetch_latest_release_returns_current_metadata_and_notes(self):
        payload, values = _release_payload("0.9.2", "0" * 64)
        payload["body"] = "修复识别和数据保存问题。"
        api_url = "https://api.github.com/repos/HX-Wrdzgzs/ham-checkin-assistant/releases/latest"
        values[api_url] = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        release = fetch_latest_release(opener=_Opener(values))
        self.assertEqual(release.version, "0.9.2")
        self.assertEqual(release.release_notes, "修复识别和数据保存问题。")

    def test_download_update_verifies_sha256(self):
        exe = b"verified-exe-content"
        digest = hashlib.sha256(exe).hexdigest()
        _payload, values = _release_payload("0.9.2", digest)
        release = check_latest_release("0.9.1", opener=_Opener(values))
        assert release is not None
        values[release.download_url] = exe
        downloaded = download_update(release, opener=_Opener(values))
        try:
            self.assertEqual(downloaded.read_bytes(), exe)
        finally:
            downloaded.unlink(missing_ok=True)

    def test_download_update_rejects_checksum_mismatch(self):
        exe = b"different-exe"
        _payload, values = _release_payload("0.9.2", "0" * 64)
        release = check_latest_release("0.9.1", opener=_Opener(values))
        assert release is not None
        values[release.download_url] = exe
        with self.assertRaisesRegex(UpdateError, "SHA256"):
            download_update(release, opener=_Opener(values))

    def test_download_update_retries_transient_checksum_mismatch(self):
        good_exe = b"eventually-verified-exe"
        digest = hashlib.sha256(good_exe).hexdigest()
        _payload, values = _release_payload("0.9.2", digest)
        release = check_latest_release("0.9.1", opener=_Opener(values))
        assert release is not None
        opener = _SequenceOpener([b"partial-response", good_exe])
        downloaded = download_update(release, opener=opener)
        try:
            self.assertEqual(downloaded.read_bytes(), good_exe)
            self.assertEqual(len(opener.urls), 2)
            self.assertIn("ham_update_retry=1-", opener.urls[1])
        finally:
            downloaded.unlink(missing_ok=True)

    def test_download_update_requires_checksum(self):
        _payload, values = _release_payload("0.9.2", None)
        release = check_latest_release("0.9.1", opener=_Opener(values))
        assert release is not None
        values[release.download_url] = b"unverified"
        with self.assertRaisesRegex(UpdateError, "SHA256"):
            download_update(release, opener=_Opener(values))

    def test_check_latest_release_falls_back_to_legacy_manifest(self):
        """main 清单暂不可用时，兼容旧版客户端使用的过渡分支清单。"""
        manifest = {
            "version": "0.9.4",
            "tag_name": "v0.9.4",
            "html_url": "https://github.com/HX-Wrdzgzs/ham-checkin-assistant/releases/tag/v0.9.4",
            "download_url": "https://github.com/HX-Wrdzgzs/ham-checkin-assistant/releases/download/v0.9.4/HAM.exe",
            "sha256": "b" * 64,
        }
        with mock.patch(
            "services.update_service._read_url",
            side_effect=[
                UpdateError("HTTP 403"),
                UpdateError("main manifest 404"),
                json.dumps(manifest).encode(),
            ],
        ):
            release = check_latest_release("0.9.3")
        self.assertIsNotNone(release)
        self.assertEqual(release.version, "0.9.4")
        self.assertEqual(release.expected_sha256, "b" * 64)

    def test_check_latest_release_falls_back_to_public_manifest(self):
        manifest = {
            "version": "0.9.2",
            "tag_name": "v0.9.2",
            "html_url": "https://github.com/HX-Wrdzgzs/ham-checkin-assistant/releases/tag/v0.9.2",
            "download_url": "https://github.com/HX-Wrdzgzs/ham-checkin-assistant/releases/download/v0.9.2/HAM.exe",
            "sha256": "a" * 64,
        }
        with mock.patch(
            "services.update_service._read_url",
            side_effect=[UpdateError("HTTP 403"), json.dumps(manifest).encode()],
        ):
            release = check_latest_release("0.9.1")
        self.assertIsNotNone(release)
        self.assertEqual(release.download_url.rsplit("/", 1)[-1], "HAM.exe")
        self.assertEqual(release.expected_sha256, "a" * 64)


if __name__ == "__main__":
    unittest.main()
