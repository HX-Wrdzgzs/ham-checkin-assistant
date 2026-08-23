"""跨版本更新回归：冻结 v0.9.3 解析语义，验证 v0.9.4 Release 兼容资产。

v0.9.3 的真实源码来自 tag 7314da7（v0.9.3 Release）。本文件只复制它的
资产名、checksum 和 fallback 判定合同，不导入当前 updater，避免“用新代码测
旧客户端”掩盖兼容性问题。
"""
from __future__ import annotations

import json
import re
import unittest

from release import GITHUB_LEGACY_UPLOAD_ASSET_NAME, RELEASE_ASSET_NAME


REPOSITORY = "HX-Wrdzgzs/ham-checkin-assistant"
V093_ASSET_NAME = "HAM点名助手.exe"
CHECKSUM_ASSET_NAME = "SHA256SUMS.txt"
V094_SHA256 = "3fded59437d1fb7ac221b7ca553cdd326d99ab83c925ede25c37fce66c6306dc"
V094_EXE_URL = (
    f"https://github.com/{REPOSITORY}/releases/download/v0.9.4/HAM.exe"
)
V094_LEGACY_EXE_URL = (
    f"https://github.com/{REPOSITORY}/releases/download/v0.9.4/"
    f"{GITHUB_LEGACY_UPLOAD_ASSET_NAME}"
)
V094_CHECKSUM_URL = (
    f"https://github.com/{REPOSITORY}/releases/download/v0.9.4/"
    f"{CHECKSUM_ASSET_NAME}"
)


def _legacy_asset_url(assets: list[dict], name: str) -> str | None:
    """v0.9.3: name/label 必须精确匹配中文资产名。"""
    for asset in assets:
        if (str(asset.get("name") or "") == name
                or str(asset.get("label") or "") == name):
            return str(asset.get("browser_download_url") or "") or None
    return None


def _legacy_checksum_for(text: str, asset_name: str) -> str | None:
    """v0.9.3: checksum 行的文件名也必须精确匹配中文资产名。"""
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        digest, filename = parts
        if (filename.lstrip("*").strip() == asset_name
                and re.fullmatch(r"[0-9a-fA-F]{64}", digest)):
            return digest.lower()
    return None


def _v094_payload(*, include_legacy_asset: bool) -> dict:
    assets = [
        {
            "name": RELEASE_ASSET_NAME,
            "label": RELEASE_ASSET_NAME,
            "browser_download_url": V094_EXE_URL,
        },
        {
            "name": CHECKSUM_ASSET_NAME,
            "browser_download_url": V094_CHECKSUM_URL,
        },
    ]
    if include_legacy_asset:
        assets.insert(1, {
            "name": GITHUB_LEGACY_UPLOAD_ASSET_NAME,
            "label": V093_ASSET_NAME,
            "browser_download_url": V094_LEGACY_EXE_URL,
        })
    return {
        "tag_name": "v0.9.4",
        "html_url": f"https://github.com/{REPOSITORY}/releases/tag/v0.9.4",
        "assets": assets,
    }


def _legacy_api_result(payload: dict, checksum_text: str) -> tuple[str, str]:
    """执行 v0.9.3 API 资产选择的等价逻辑。"""
    download_url = _legacy_asset_url(payload["assets"], V093_ASSET_NAME)
    if not download_url:
        raise ValueError("Release 缺少 v0.9.3 可识别的中文资产")
    checksum_url = _legacy_asset_url(payload["assets"], CHECKSUM_ASSET_NAME)
    if not checksum_url:
        raise ValueError("Release 缺少 checksum 资产")
    expected = _legacy_checksum_for(checksum_text, V093_ASSET_NAME)
    if expected is None:
        raise ValueError("checksum 缺少 v0.9.3 可识别的中文文件名")
    return download_url, expected


def _legacy_manifest_result(manifest: dict) -> tuple[str, str]:
    """v0.9.3 fallback 直接读取 manifest 的 download_url/sha256。"""
    return str(manifest["download_url"]), str(manifest["sha256"]).lower()


def _legacy_check_with_fallback(
    payload: dict,
    checksum_text: str,
    manifest: dict | None,
) -> tuple[str, str]:
    """冻结 v0.9.3：API UpdateError 后才读取 codex fallback manifest。"""
    try:
        return _legacy_api_result(payload, checksum_text)
    except ValueError:
        if manifest is None:
            raise
        return _legacy_manifest_result(manifest)


class TestUpdateBackwardCompatibility(unittest.TestCase):
    def test_a_ascii_only_release_is_not_understood_by_v093_api_parser(self):
        """场景 A：只有 HAM.exe + HAM.exe checksum 时，旧 API parser 不识别。"""
        payload = _v094_payload(include_legacy_asset=False)
        checksum = f"{V094_SHA256}  {RELEASE_ASSET_NAME}\n"
        with self.assertRaisesRegex(ValueError, "中文"):
            _legacy_api_result(payload, checksum)

    def test_b_dual_assets_are_understood_by_v093(self):
        """场景 B：增加中文兼容资产后，旧客户端可以从 API 选中它。"""
        payload = _v094_payload(include_legacy_asset=True)
        checksum = f"{V094_SHA256}  {V093_ASSET_NAME}\n"
        download_url, expected = _legacy_api_result(payload, checksum)
        self.assertEqual(download_url, V094_LEGACY_EXE_URL)
        self.assertEqual(expected, V094_SHA256)

    def test_c_dual_checksum_lines_keep_both_clients_verifiable(self):
        """场景 C：同一 hash 的两条文件名记录分别满足新旧客户端。"""
        checksum = (
            f"{V094_SHA256}  {RELEASE_ASSET_NAME}\n"
            f"{V094_SHA256}  {V093_ASSET_NAME}\n"
        )
        self.assertEqual(_legacy_checksum_for(checksum, V093_ASSET_NAME), V094_SHA256)
        self.assertIn(f"{V094_SHA256}  {RELEASE_ASSET_NAME}", checksum)

    def test_d_api_failure_uses_legacy_manifest(self):
        """场景 D：API 不可用时，v0.9.3 fallback 可发现 v0.9.4。"""
        payload = _v094_payload(include_legacy_asset=False)
        checksum = f"{V094_SHA256}  {RELEASE_ASSET_NAME}\n"
        manifest = {
            "version": "0.9.4",
            "tag_name": "v0.9.4",
            "html_url": f"https://github.com/{REPOSITORY}/releases/tag/v0.9.4",
            "download_url": V094_EXE_URL,
            "asset_name": RELEASE_ASSET_NAME,
            "sha256": V094_SHA256,
        }
        download_url, expected = _legacy_check_with_fallback(payload, checksum, manifest)
        self.assertEqual(download_url, V094_EXE_URL)
        self.assertEqual(expected, V094_SHA256)

    def test_e_api_asset_mismatch_reaches_fallback_in_real_v093_semantics(self):
        """场景 E：API 正常但附件名不兼容时，旧源码会进入 fallback，而非直接返回 None。"""
        payload = _v094_payload(include_legacy_asset=False)
        checksum = f"{V094_SHA256}  {RELEASE_ASSET_NAME}\n"
        manifest = {
            "version": "0.9.4",
            "tag_name": "v0.9.4",
            "download_url": V094_EXE_URL,
            "sha256": V094_SHA256,
        }
        download_url, expected = _legacy_check_with_fallback(payload, checksum, manifest)
        self.assertEqual(download_url, V094_EXE_URL)
        self.assertEqual(expected, V094_SHA256)

    def test_f_release_metadata_keeps_main_manifest_shape(self):
        """主 manifest 仍以 HAM.exe 为稳定格式，不改旧版 fallback 的语义。"""
        manifest = {
            "version": "0.9.4",
            "tag_name": "v0.9.4",
            "download_url": V094_EXE_URL,
            "asset_name": RELEASE_ASSET_NAME,
            "sha256": V094_SHA256,
        }
        encoded = json.dumps(manifest, ensure_ascii=False)
        self.assertEqual(json.loads(encoded)["asset_name"], "HAM.exe")
        self.assertEqual(len(V094_SHA256), 64)

    def test_release_urls_are_github_download_urls(self):
        for url in (V094_EXE_URL, V094_LEGACY_EXE_URL, V094_CHECKSUM_URL):
            self.assertTrue(url.startswith(
                f"https://github.com/{REPOSITORY}/releases/download/v0.9.4/"))


if __name__ == "__main__":
    unittest.main()
