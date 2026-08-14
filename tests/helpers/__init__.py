"""测试辅助工厂：所有测试使用隔离的 config/DB/Excel，绝不触碰真实运行时数据。

约定：
- 每个测试用 make_settings() 得到「临时目录 + 指向临时 config.json 的 Settings」。
- 禁止在测试里直接调用默认 Settings()（那会指向真实 config.json）。
- Excel 相关一律用临时工作簿 / Mock COM，禁止操作用户真实点名表。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from config.settings import CONFIG_PATH, Settings


def make_settings() -> tuple[Settings, Path]:
    """返回 (隔离 Settings, 临时根目录)。config.json 位于临时目录，不触碰真实配置。"""
    tmp = Path(tempfile.mkdtemp(prefix="ham_test_"))
    s = Settings(path=tmp / "config.json")
    s.set_many(
        data_dir=str(tmp / "data"),
        logs_dir=str(tmp / "logs"),
        backup_dir=str(tmp / "backup"),
        excel_template="",
        excel_sheet_name="",
    )
    return s, tmp


def make_service():
    """构建 AppService（临时库 + 临时配置），返回 svc。"""
    s, _tmp = make_settings()
    from services.app_service import AppService

    return AppService(s)


def assert_real_config_untouched(testcase, before: str | None) -> None:
    """校验真实 config.json 与 before（SHA256）一致；before=None 表示当时不存在。"""
    import hashlib

    if before is None:
        testcase.assertFalse(CONFIG_PATH.exists(),
                             "测试不应创建真实 config.json")
        return
    if not CONFIG_PATH.exists():
        testcase.fail("真实 config.json 不应被删除")
    after = hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest()
    testcase.assertEqual(before, after, "测试修改了真实 config.json！")


def real_config_sha() -> str | None:
    """真实 config.json 当前 SHA256；不存在返回 None。"""
    import hashlib

    if not CONFIG_PATH.exists():
        return None
    return hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest()
