"""七轮完整 Benchmark：性能 / 资源 / 调用 / 快捷性。
纯本地跑，不写真实数据（全部用临时目录）。
"""
from __future__ import annotations

import ctypes
import gc
import os
import sqlite3
import statistics
import tempfile
import time
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ctypes import wintypes

_psapi = ctypes.WinDLL("psapi")
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)


class _PMC(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
    ]


_psapi.GetProcessMemoryInfo.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
_psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
_k32.GetCurrentProcess.restype = wintypes.HANDLE


def rss_mb() -> float:
    pmc = _PMC(); pmc.cb = ctypes.sizeof(_PMC)
    h = _k32.GetCurrentProcess()
    if _psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
        return pmc.WorkingSetSize / 1048576.0
    return -1.0


def bench(fn, n=1):
    """运行 fn n 次，返回 (单次最小, 中位, 总, 吞吐每秒)。"""
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    tmin = min(times); tmed = statistics.median(times)
    return tmin, tmed, sum(times), n / sum(times)


def fmt(ms):
    return f"{ms*1000:8.1f}ms"


OUT = []


def row(label, tmin, tmed, extra=""):
    OUT.append(f"| {label} | {tmin*1000:9.2f}ms | {tmed*1000:9.2f}ms | {extra} |")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="ham_bench_"))
    from config.settings import Settings
    # 隔离 config：benchmark 不得写真实 config.json（任务书第一阶段 #1）
    s = Settings(path=tmp / "config.json")
    s.set_many(data_dir=str(tmp / "data"), logs_dir=str(tmp / "logs"), backup_dir=str(tmp / "backup"))

    t0 = time.perf_counter()
    from services.app_service import AppService
    svc = AppService(s)
    init_ms = (time.perf_counter() - t0) * 1000
    rss0 = rss_mb()

    # 建立场次并预热少量历史（供历史补全 / 预测场景）
    svc.create_session(name="bench", date="2026-08-10")
    samples = [
        "bg4tki njqx k6 y 5",
        "bd4xwm njgl ft857d 771 10",
        "bg4rll njjy g90 y 5",
        "bh4daf njyht id52 771 5",
        "bg4xhz njqh uv5r 771 5",
        "bd4skj njpk gm300 771 25",
    ]
    for txt in samples:
        svc.commit(svc.parse(txt))

    # 预热缓存（与真实启动一致）
    svc.parser.invalidate_caches()
    svc._value_frequency()

    # ============ 轮1：启动与初始化 ============
    print("\n===== 轮1 启动与初始化（AppService 冷启动） =====")
    print(f"| 项目 | 耗时 |")
    print(f"| AppService 初始化（建库+seed+预热缓存） | {init_ms:8.1f}ms |")
    print(f"| 初始化后进程内存 | {rss0:8.1f} MB |")

    # ============ 轮2：解析性能 ============
    print("\n===== 轮2 Parser 解析性能（各场景 100 次） =====")
    scenes = {
        "标准乱序 bg4tki njqx k6 y 5": "bg4tki njqx k6 y 5",
        "缩写QTH bg4tki njqx k6 y 5(拼音)": "bg4tki njqx k6 y 5",
        "设备别名 1907": "bg4tki njqx 1907 y 5",
        "设备别名 id52": "bg4tki njjy id52 771 5",
        "纯数字功率 bg4tki njqx 5": "bg4tki njqx 5",
        "南京南不折叠 bg4tki 南京南 k6": "bg4tki 南京南 k6",
        "拼音QTH bd4xwm xuanwu k6": "bd4xwm xuanwu k6",
        "模糊错拼 bg4tki nanjing k6": "bg4tki nanjing k6",
        "历史补全 bg4tki(已有历史)": "bg4tki",
        "完整长串 全字段乱序": "y 5 k6 njqx bg4tki",
    }
    OUT.append("| 场景 | 最快 | 中位 | 吞吐(次/s) |")
    for label, txt in scenes.items():
        try:
            tmin, tmed, _, thr = bench(lambda: svc.parse(txt), n=100)
            row(label, tmin, tmed, f"{thr:.0f}")
        except Exception as e:
            row(label, -1, -1, f"ERR {type(e).__name__}")
    print("\n".join(OUT)); OUT.clear()

    # ============ 轮3：录入/提交性能 ============
    print("\n===== 轮3 录入/提交性能（150 条，无 Excel） =====")
    svc2_settings = Settings(path=tmp / "config2.json"); svc2_settings.set_many(
        data_dir=str(tmp / "data2"), logs_dir=str(tmp / "logs2"), backup_dir=str(tmp / "backup2"))
    from services.app_service import AppService as _AS
    svc2 = _AS(svc2_settings)
    svc2.create_session(name="bench150", date="2026-08-10")
    calls = [f"bg{i % 60:02d}xyz" for i in range(150)]
    t0 = time.perf_counter()
    for i, cs in enumerate(calls):
        svc2.commit(svc2.parse(f"{cs} njqx k6 y 5"))
    dt = time.perf_counter() - t0
    print(f"| 150 条提交总耗时 | {dt*1000:8.1f}ms |")
    print(f"| 平均每条 | {dt/150*1000:8.1f}ms | 吞吐 {150/dt:.0f} 条/s |")

    # ============ 轮4：补全 / 快捷性 ============
    print("\n===== 轮4 输入补全 / 快捷性（各 200 次） =====")
    comp_tests = {
        "complete('njq') QTH缩写候选": "njq",
        "complete('id5') 设备候选": "id5",
        "complete('77') 天线候选": "77",
        "complete_callsign('rll') 呼号库": "rll",
        "token_is_complete('njqx')": None,
        "token_is_complete('yz')": None,
        "token_is_complete('ba4rll')": None,
    }
    OUT.append("| 操作 | 最快 | 中位 | 吞吐(次/s) |")
    for label, tok in comp_tests.items():
        if tok is None:
            tok = label.split("'")[1]
        try:
            fn = (lambda t: (lambda: svc.token_is_complete(t)))(tok)
            if label.startswith("complete_callsign"):
                fn = (lambda t: (lambda: svc.complete_callsign(t)))(tok)
            elif label.startswith("complete("):
                fn = (lambda t: (lambda: svc.complete(t)))(tok)
            tmin, tmed, _, thr = bench(fn, n=200)
            row(label, tmin, tmed, f"{thr:.0f}")
        except Exception as e:
            row(label, -1, -1, f"ERR {type(e).__name__}")
    print("\n".join(OUT)); OUT.clear()

    # ============ 轮5：模糊匹配 ============
    print("\n===== 轮5 模糊匹配（RapidFuzz） =====")
    from core.fuzzy_resolver import fuzzy_resolve, fuzzy_resolve_pinyin
    from normalizers.region_index import RegionIndex
    ri = RegionIndex()
    opts_str = [(e.initials if hasattr(e, 'initials') else k, e.display) for k, es in ri.by_initials.items() for e in es[:1]][:200]
    opts_py = []
    for k, es in list(ri.by_initials.items())[:200]:
        e = es[0]
        py = e.pinyin if hasattr(e, 'pinyin') else ""
        opts_py.append((k, e.display, py, 0.0))
    qth_fuzzy = [o for o in opts_py[:80]]
    OUT.append("| 操作 | 最快 | 中位 | 吞吐(次/s) |")
    try:
        tmin, tmed, _, thr = bench(lambda: fuzzy_resolve("nanjing", opts_str), n=200)
        row("fuzzy_resolve('nanjing') 200选项", tmin, tmed, f"{thr:.0f}")
    except Exception as e:
        row("fuzzy_resolve", -1, -1, f"ERR {type(e).__name__}")
    try:
        tmin, tmed, _, thr = bench(lambda: fuzzy_resolve_pinyin("njq", qth_fuzzy), n=200)
        row("fuzzy_resolve_pinyin('njq') 80选项", tmin, tmed, f"{thr:.0f}")
    except Exception as e:
        row("fuzzy_resolve_pinyin", -1, -1, f"ERR {type(e).__name__}")
    try:
        tmin, tmed, _, thr = bench(lambda: ri.resolve_initials("yz"), n=200)
        row("region.resolve_initials('yz')", tmin, tmed, f"{thr:.0f}")
    except Exception as e:
        row("resolve_initials", -1, -1, f"ERR {type(e).__name__}")
    print("\n".join(OUT)); OUT.clear()

    # ============ 轮6：数据库 / 大数据集 ============
    print("\n===== 轮6 数据库 / 大数据集（复制真实 dist 库 4138 条） =====")
    src_db = Path(r"h:\HAM EXCEL\dist\HAM点名助手\data\ham_checkin.db")
    if src_db.exists():
        big = Path(tmp / "big.db")
        try:
            t0 = time.perf_counter()
            s1 = sqlite3.connect(str(src_db)); s2 = sqlite3.connect(str(big))
            s1.backup(s2); s2.close(); s1.close()
            copy_ms = (time.perf_counter() - t0) * 1000
            print(f"| 复制 4138 条库到临时 | {copy_ms:8.1f}ms |")
            from database.db import connect
            conn = connect(big)
            from database.repository import Repository
            repo = Repository(conn)
            n = conn.execute("SELECT COUNT(*) FROM checkins").fetchone()[0]
            print(f"| 大数据集规模 | {n} 条 |")
            t0 = time.perf_counter()
            repo.rebuild_profiles()
            rebuild_ms = (time.perf_counter() - t0) * 1000
            print(f"| rebuild_profiles 全量画像重建 | {rebuild_ms:8.1f}ms |")
            tmin, tmed, _, thr = bench(lambda: repo.search_stations("ba4r"), n=200)
            row("search_stations('ba4r')", tmin, tmed, f"{thr:.0f}")
            tmin, tmed, _, thr = bench(lambda: repo.search_stations("nj"), n=200)
            row("search_stations('nj')", tmin, tmed, f"{thr:.0f}")
            print("\n".join(OUT)); OUT.clear()
        except Exception:
            print("  大数据集测试失败:", traceback.format_exc().splitlines()[-1])
    else:
        print("  dist 库不存在，跳过")

    # ============ 轮7：资源占用 ============
    print("\n===== 轮7 资源占用 =====")
    gc.collect()
    rss_now = rss_mb()
    db_sz = tmp / "data" / "ham_checkin.db"
    sz = db_sz.stat().st_size / 1024 if db_sz.exists() else 0
    print(f"| 项目 | 值 |")
    print(f"| 当前进程内存 WorkingSet | {rss_now:8.1f} MB |")
    print(f"| 150 条库文件大小 | {sz:8.1f} KB |")
    print(f"| 线程数 | {len(__import__('threading').enumerate())} |")

    print("\n===== 结束 =====")
    try:
        svc.close()
    except Exception:
        pass
    print("BENCH_DONE")


if __name__ == "__main__":
    main()
