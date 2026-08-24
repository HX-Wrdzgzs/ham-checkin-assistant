"""关于、版本和支持信息窗口。"""
from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QTextBrowser,
    QVBoxLayout,
)

from services.update_service import ReleaseInfo, version_key
from version import __version__

PROJECT_URL = "https://github.com/HX-Wrdzgzs/ham-checkin-assistant"
RELEASES_URL = f"{PROJECT_URL}/releases/latest"
SPONSOR_URL = "https://www.ifdian.net/a/wrdzgzs?utm_source=copylink&utm_medium=link"


class AboutDialog(QDialog):
    """展示本地版本、云端 Release、更新说明和项目支持方式。"""

    refresh_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("关于 / 版本")
        self.resize(680, 560)
        self._release: ReleaseInfo | None = None

        title = QLabel("<h2>江苏省中继 HAM 智能点名录入助手</h2>")
        title.setTextFormat(Qt.TextFormat.RichText)
        description = QLabel(
            "本软件永久免费使用，帮助业余无线电点名时更快录入、整理和同步 Excel。"
            "软件不依赖 AI、Token 或云端数据库，点名数据仍保存在本机。"
        )
        description.setWordWrap(True)

        version_row = QHBoxLayout()
        self.local_version_label = QLabel(f"当前版本：{__version__}")
        self.cloud_version_label = QLabel("云端最新版本：正在查询…")
        version_row.addWidget(self.local_version_label)
        version_row.addSpacing(24)
        version_row.addWidget(self.cloud_version_label)
        version_row.addStretch()

        self.status_label = QLabel("版本信息会从公开 GitHub Release 读取。")
        self.status_label.setWordWrap(True)

        notes_title = QLabel("<b>更新说明</b>")
        self.notes_browser = QTextBrowser()
        self.notes_browser.setOpenExternalLinks(True)
        self.notes_browser.setReadOnly(True)
        self.notes_browser.setPlainText(
            "正在读取云端 Release 的更新说明…\n\n"
            "如果网络暂时不可用，仍可以打开 GitHub 更新页查看。"
        )

        github_button = QPushButton("打开 GitHub 项目")
        github_button.clicked.connect(lambda: webbrowser.open(PROJECT_URL))
        self.release_button = QPushButton("查看 GitHub 更新页")
        self.release_button.setEnabled(False)
        self.release_button.clicked.connect(self._open_release_page)
        self.sponsor_button = QPushButton("自愿赞助支持")
        self.sponsor_button.clicked.connect(lambda: webbrowser.open(SPONSOR_URL))
        self.refresh_button = QPushButton("刷新云端版本")
        self.refresh_button.clicked.connect(self.refresh_requested.emit)

        link_row = QHBoxLayout()
        link_row.addWidget(github_button)
        link_row.addWidget(self.release_button)
        link_row.addWidget(self.sponsor_button)
        link_row.addWidget(self.refresh_button)
        link_row.addStretch()

        free_label = QLabel(
            "<b>永久免费声明：</b>本软件持续免费，不因版本更新增加功能收费。"
            "如果它对你的点名工作有帮助，欢迎按自己的意愿赞助；赞助不会影响功能、更新或数据安全。"
        )
        free_label.setWordWrap(True)
        address_label = QLabel(
            "<b>官方项目地址：</b>目前以 GitHub 项目仓库作为官方发布地址；"
            "暂未设置独立官网，后续有正式域名时再补充。"
        )
        address_label.setWordWrap(True)

        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addLayout(version_row)
        layout.addWidget(self.status_label)
        layout.addWidget(notes_title)
        layout.addWidget(self.notes_browser, 1)
        layout.addLayout(link_row)
        layout.addWidget(free_label)
        layout.addWidget(address_label)
        layout.addWidget(close_box)

    def set_loading(self) -> None:
        self.cloud_version_label.setText("云端最新版本：正在查询…")
        self.status_label.setText("正在读取 GitHub Release，请稍候；不会影响点名和 Excel。")
        self.refresh_button.setEnabled(False)

    def set_release(self, release: ReleaseInfo | None, error: str | None = None) -> None:
        self.refresh_button.setEnabled(True)
        self._release = release
        if error:
            self.cloud_version_label.setText("云端最新版本：暂时无法获取")
            self.status_label.setText(
                f"读取云端版本失败：{error}\n本地功能不受影响，可稍后重试或打开 GitHub 更新页。"
            )
            self.release_button.setEnabled(True)
            self.notes_browser.setPlainText(
                "本次没有拿到云端更新正文。\n\n"
                "请点击“查看 GitHub 更新页”查看每个版本的完整更新说明。"
            )
            return
        if release is None:
            self.cloud_version_label.setText("云端最新版本：未返回有效版本")
            self.status_label.setText("GitHub 返回的数据不完整，请稍后重试。")
            self.release_button.setEnabled(False)
            self.notes_browser.setPlainText("暂无更新说明。")
            return

        self.release_button.setEnabled(True)
        try:
            is_newer = version_key(release.version) > version_key(__version__)
        except Exception:  # noqa: BLE001
            is_newer = False
        suffix = "（有新版本可用）" if is_newer else "（当前已是最新）"
        self.cloud_version_label.setText(f"云端最新版本：{release.version} {suffix}")
        published = release.published_at[:10] if release.published_at else ""
        source = f"GitHub Release {release.tag_name}"
        if published:
            source += f"，发布日期 {published}"
        self.status_label.setText(source)

        notes = release.release_notes.strip()
        if notes:
            self.notes_browser.setMarkdown(notes)
        else:
            self.notes_browser.setPlainText(
                "该 Release 没有提供文字版更新说明。\n\n"
                "请点击“查看 GitHub 更新页”查看附件和完整发布内容。"
            )

    def _open_release_page(self) -> None:
        url = self._release.html_url if self._release is not None else RELEASES_URL
        webbrowser.open(url or RELEASES_URL)
