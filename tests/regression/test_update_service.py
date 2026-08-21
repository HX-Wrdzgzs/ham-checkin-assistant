"""自动更新服务的离线回归测试：不访问真实 GitHub，不启动替换脚本。"""
from __future__ import annotations

import hashlib
import json
import unittest

from services.update_service import (
    CHECKSUM_ASSET_NAME,
    UPDATE_ASSET_NAME,
    UpdateError,
    check_latest_release,
    download_update,
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

    def __call__(self, request, timeout: float):
        del timeout
        return _Response(self.values[request.full_url])


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
            {"name": UPDATE_ASSET_NAME, "browser_download_url": exe_url},
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

    def test_download_update_requires_checksum(self):
        _payload, values = _release_payload("0.9.2", None)
        release = check_latest_release("0.9.1", opener=_Opener(values))
        assert release is not None
        values[release.download_url] = b"unverified"
        with self.assertRaisesRegex(UpdateError, "SHA256"):
            download_update(release, opener=_Opener(values))


if __name__ == "__main__":
    unittest.main()
