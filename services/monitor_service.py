"""NRL Nanny 只读监听服务（第四阶段）。

职责：
- 启动/停止监听（后台轮询线程）
- 断线重连（网络错误 → degraded/error → 自动重试）
- 状态显示：offline / connecting / online / degraded / error
- 最近活动 + 候选呼号回调（供 UI 点击填入 QuickInput）
- **绝不写数据库、绝不自动提交签到**（只提供候选）

线程模型：单后台线程 + threading.Event 停止；stop() 安全 join，
应用退出期间调用 stop() 不会悬挂（socket timeout 有限）。
"""
from __future__ import annotations

import logging
import threading

import requests

from providers.nrl_nanny import NrlNannyProvider, parse_activity

logger = logging.getLogger("ham.nrl")

# 状态机取值
OFFLINE = "offline"
CONNECTING = "connecting"
ONLINE = "online"
DEGRADED = "degraded"
ERROR = "error"


class MonitorService:
    """NRL Nanny 监听服务。只读，无 DB 写入。"""

    def __init__(self, url: str = "", poll_interval: float = 5.0,
                 timeout: float = 8.0, max_retries: int = 3) -> None:
        self.provider = NrlNannyProvider(url=url, timeout=timeout)
        self.poll_interval = max(1.0, float(poll_interval))
        self.max_retries = max_retries
        self.state = OFFLINE
        self.status_text = ""
        self.recent_activity: list[dict] = []   # 最近活动（原始内容保留）
        self.candidates: list[str] = []         # 最新一批候选呼号
        self._thread: threading.Thread | None = None
        self._stop_evt = threading.Event()
        self._lock = threading.RLock()  # 可重入：start() 持锁时 _set_state 再次加锁
        # 回调（UI 订阅；都在调用线程触发，UI 需自行 marshal 到主线程）
        self.on_state = None      # fn(state, msg)
        self.on_activity = None   # fn(entries: list[dict])
        self.on_candidates = None # fn(candidates: list[str])

    # ---------- 生命周期 ----------
    def start(self) -> bool:
        """启动监听。已在运行则返回 False。"""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop_evt.clear()
            self._set_state(CONNECTING, "正在连接 NRL Nanny…")
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="nrl-monitor")
            self._thread.start()
            return True

    def stop(self) -> None:
        """停止监听并安全 join 线程（应用退出期间调用安全）。"""
        self._stop_evt.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=max(3.0, self.provider.timeout + 1.0))
        with self._lock:
            self._thread = None
        self._set_state(OFFLINE, "已停止监听")
        try:
            self.provider.session.close()
        except Exception:  # noqa: BLE001
            pass

    def reconnect(self) -> bool:
        """强制断线重连：未运行则启动；运行中则触发一次立即拉取。"""
        if self._thread is None or not self._thread.is_alive():
            return self.start()
        return True

    # ---------- 内部 ----------
    def _run(self) -> None:
        failures = 0
        while not self._stop_evt.is_set():
            if self.state != ONLINE:
                self._set_state(CONNECTING, "正在连接 NRL Nanny…")
            try:
                res = self.provider.fetch()
                failures = 0
                entries = parse_activity(res.get("raw", ""))
                with self._lock:
                    self.candidates = list(res.get("candidates", []))
                    if entries:
                        self.recent_activity = (entries + self.recent_activity)[:50]
                    self.status_text = (f"在线（{len(entries)} 条活动）"
                                        if res.get("ok") else res.get("error", ""))
                self._set_state(ONLINE, self.status_text)
                if self.on_activity and entries:
                    try:
                        self.on_activity(entries)
                    except Exception:  # noqa: BLE001
                        logger.exception("on_activity callback failed")
                if self.on_candidates:
                    try:
                        self.on_candidates(list(self.candidates))
                    except Exception:  # noqa: BLE001
                        logger.exception("on_candidates callback failed")
            except (requests.Timeout, requests.ConnectionError,
                    requests.RequestException) as e:
                failures += 1
                self._set_state(
                    DEGRADED if failures < self.max_retries else ERROR,
                    f"网络错误：{e}")
                # 失败重连间隔递增，避免高频打网络
                wait = self.poll_interval * min(failures, self.max_retries)
                if self._stop_evt.wait(timeout=wait):
                    break
                continue
            except Exception as e:  # noqa: BLE001
                failures += 1
                self._set_state(ERROR, f"监听异常：{e}")
            if self._stop_evt.wait(timeout=self.poll_interval):
                break

    def _set_state(self, state: str, msg: str) -> None:
        with self._lock:
            self.state = state
            self.status_text = msg
        cb = self.on_state
        if cb:
            try:
                cb(state, msg)
            except Exception:  # noqa: BLE001
                logger.exception("on_state callback failed")
