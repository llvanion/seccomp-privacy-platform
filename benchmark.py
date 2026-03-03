# -*- coding: utf-8 -*-
"""
SSE 加密性能基准测试
====================
测试各 SSE 方案（CJJ14.PiBas、CJJ14.Pi2Lev、CT14.Pi、DP17.Pi）
在 KeyGen、EDBSetup（加密建库）、TokenGen（陷门生成）、Search（搜索）
四个阶段的耗时，并与等价的明文字典操作对比，量化加密带来的性能损失。

用法:
    python benchmark.py
    python benchmark.py --keywords 500 --entries 50 --repeat 3
"""

import argparse
import os
import time
import statistics
import json
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Callable, List, Dict, Any

import matplotlib.pyplot as plt
import matplotlib
import matplotlib.font_manager as fm
import warnings

# 配置中文字体
_HAS_CHINESE_FONT = False

def _setup_matplotlib_fonts():
    """配置 matplotlib 中文字体支持"""
    global _HAS_CHINESE_FONT
    available_fonts = set([f.name for f in fm.fontManager.ttflist])
    
    # 尝试常见的中文字体（按优先级排序）
    chinese_fonts = [
        'Microsoft YaHei', 'SimHei', 'SimSun', 'KaiTi', 'FangSong',
        'Arial Unicode MS', 'Noto Sans CJK SC', 'WenQuanYi Micro Hei'
    ]
    
    found_font = None
    for font in chinese_fonts:
        if font in available_fonts:
            found_font = font
            break
    
    if found_font:
        matplotlib.rcParams['font.sans-serif'] = [found_font]
        _HAS_CHINESE_FONT = True
        print(f"✓ 使用中文字体: {found_font}")
    else:
        # 降级到英文，禁用字体警告
        matplotlib.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial']
        warnings.filterwarnings('ignore', category=UserWarning, module='matplotlib.font_manager')
        _HAS_CHINESE_FONT = False
        print("⚠ 未找到中文字体，图表将使用英文标签")
    
    matplotlib.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题

_setup_matplotlib_fonts()

# 根据字体可用性定义标签
LABELS = {
    'plaintext': '明文基准' if _HAS_CHINESE_FONT else 'Plaintext',
    'scheme': '方案' if _HAS_CHINESE_FONT else 'Scheme',
    'build_time': '建库时间 (ms)' if _HAS_CHINESE_FONT else 'Build Time (ms)',
    'edb_title': '加密数据库建立时间对比' if _HAS_CHINESE_FONT else 'Encrypted Database Setup Time Comparison',
    'search_time': '单次搜索时间 (ms/keyword)' if _HAS_CHINESE_FONT else 'Search Time (ms/keyword)',
    'search_title': '加密搜索时间对比' if _HAS_CHINESE_FONT else 'Encrypted Search Time Comparison',
    'sse_scheme': 'SSE 方案' if _HAS_CHINESE_FONT else 'SSE Scheme',
    'overhead_ratio': '相对明文基准的倍数' if _HAS_CHINESE_FONT else 'Overhead Ratio (vs Plaintext)',
    'overhead_title': '加密带来的性能损失（倍数）' if _HAS_CHINESE_FONT else 'Encryption Overhead (Ratio)',
    'build_overhead': '建库开销' if _HAS_CHINESE_FONT else 'Build Overhead',
    'search_overhead': '搜索开销' if _HAS_CHINESE_FONT else 'Search Overhead',
    'time_breakdown': '各方案操作时间分解' if _HAS_CHINESE_FONT else 'Operation Time Breakdown',
    'cumulative_time': '累计时间 (ms)' if _HAS_CHINESE_FONT else 'Cumulative Time (ms)',
    'tokengen_total': 'TokenGen (总计)' if _HAS_CHINESE_FONT else 'TokenGen (Total)',
    'search_total': 'Search (总计)' if _HAS_CHINESE_FONT else 'Search (Total)',
}


from test.tools.faker import fake_db_for_inverted_index_based_sse

# ──────────────────────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────────────────────
KEYWORD_SIZE = 16   # bytes
FILE_ID_SIZE = 8    # bytes
COL_WIDTH = 14


# ──────────────────────────────────────────────────────────────────────────────
# 数据类
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class BenchResult:
    scheme_name: str
    keyword_count: int
    avg_entries_per_keyword: float
    keygen_ms: float
    edbsetup_ms: float
    tokengen_ms: float          # per keyword average
    search_ms: float            # per keyword average
    total_entries: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PlaintextResult:
    keyword_count: int
    avg_entries_per_keyword: float
    build_ms: float
    lookup_ms: float            # per keyword average
    total_entries: int

    def to_dict(self) -> dict:
        return asdict(self)


# ──────────────────────────────────────────────────────────────────────────────
# 计时工具
# ──────────────────────────────────────────────────────────────────────────────
def _ms(start: float, end: float) -> float:
    return (end - start) * 1000.0


def _timed(fn: Callable, *args, **kwargs):
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    t1 = time.perf_counter()
    return result, _ms(t0, t1)


# ──────────────────────────────────────────────────────────────────────────────
# 明文基准（对照组）
# ──────────────────────────────────────────────────────────────────────────────
def bench_plaintext(db: dict) -> PlaintextResult:
    keywords = list(db.keys())
    total_entries = sum(len(v) for v in db.values())

    # Build: 复制字典（模拟建库）
    _, build_ms = _timed(lambda: dict(db))

    # Lookup: 依次查询每个 keyword
    t0 = time.perf_counter()
    for kw in keywords:
        _ = db[kw]
    t1 = time.perf_counter()
    lookup_ms = _ms(t0, t1) / len(keywords) if keywords else 0.0

    return PlaintextResult(
        keyword_count=len(keywords),
        avg_entries_per_keyword=total_entries / len(keywords) if keywords else 0,
        build_ms=build_ms,
        lookup_ms=lookup_ms,
        total_entries=total_entries,
    )


# ──────────────────────────────────────────────────────────────────────────────
# SSE 方案基准
# ──────────────────────────────────────────────────────────────────────────────
def bench_scheme(
    scheme_name: str,
    SchemeClass,
    config: dict,
    db: dict,
) -> BenchResult:
    keywords = list(db.keys())
    total_entries = sum(len(v) for v in db.values())

    # 1. KeyGen
    scheme = SchemeClass(config)
    key, keygen_ms = _timed(scheme.KeyGen)

    # 2. EDBSetup
    edb, edbsetup_ms = _timed(scheme.EDBSetup, key, db)

    # 3. TokenGen（所有 keyword，取平均）
    tokens = []
    t0 = time.perf_counter()
    for kw in keywords:
        tokens.append(scheme.TokenGen(key, kw))
    t1 = time.perf_counter()
    tokengen_ms = _ms(t0, t1) / len(keywords) if keywords else 0.0

    # 4. Search（所有 keyword，取平均）
    t0 = time.perf_counter()
    for tk in tokens:
        scheme.Search(edb, tk)
    t1 = time.perf_counter()
    search_ms = _ms(t0, t1) / len(keywords) if keywords else 0.0

    return BenchResult(
        scheme_name=scheme_name,
        keyword_count=len(keywords),
        avg_entries_per_keyword=total_entries / len(keywords) if keywords else 0,
        keygen_ms=keygen_ms,
        edbsetup_ms=edbsetup_ms,
        tokengen_ms=tokengen_ms,
        search_ms=search_ms,
        total_entries=total_entries,
    )


# ──────────────────────────────────────────────────────────────────────────────
# 重复运行取平均
# ──────────────────────────────────────────────────────────────────────────────
def run_repeated(fn: Callable, repeat: int) -> Any:
    """运行 fn() repeat 次，返回最后一次结果（数值字段取平均）"""
    results = [fn() for _ in range(repeat)]
    if repeat == 1:
        return results[0]

    # 对数值字段取均值
    r0 = results[0]
    if isinstance(r0, BenchResult):
        numeric_fields = ["keygen_ms", "edbsetup_ms", "tokengen_ms", "search_ms"]
        for f in numeric_fields:
            avg = statistics.mean(getattr(r, f) for r in results)
            setattr(r0, f, avg)
    elif isinstance(r0, PlaintextResult):
        r0.build_ms = statistics.mean(r.build_ms for r in results)
        r0.lookup_ms = statistics.mean(r.lookup_ms for r in results)
    return r0


# ──────────────────────────────────────────────────────────────────────────────
# 打印结果
# ──────────────────────────────────────────────────────────────────────────────
def _cell(val, width=COL_WIDTH) -> str:
    return str(val).rjust(width)


def print_results(pt: PlaintextResult, sse_results: List[BenchResult], repeat: int):
    sep = "─" * (COL_WIDTH * 7 + 2)

    print()
    print("=" * len(sep))
    print("  SSE 加密性能基准测试结果")
    print(f"  关键词数量: {pt.keyword_count}  |  平均每关键词条目数: {pt.avg_entries_per_keyword:.1f}")
    print(f"  总条目数:   {pt.total_entries}  |  重复次数: {repeat}")
    print("=" * len(sep))

    # ── 明文对照 ──────────────────────────────────────────────────────────────
    print("\n【明文字典（对照组）】")
    print(f"  建库耗时:     {pt.build_ms:>10.3f} ms  (总计)")
    print(f"  单次查询耗时: {pt.lookup_ms:>10.6f} ms  (平均每关键词)")

    # ── SSE 方案对比表 ────────────────────────────────────────────────────────
    headers = ["方案", "KeyGen(ms)", "EDBSetup(ms)", "陷门生成(ms/kw)", "搜索(ms/kw)",
               "EDB/明文建库", "搜索/明文查询"]
    print()
    print("【SSE 方案性能对比】")
    header_line = "".join(h.rjust(COL_WIDTH) for h in headers)
    print(header_line)
    print(sep)

    for r in sse_results:
        edb_overhead = f"{r.edbsetup_ms / pt.build_ms:.1f}x" if pt.build_ms > 0 else "N/A"
        search_overhead = f"{r.search_ms / pt.lookup_ms:.1f}x" if pt.lookup_ms > 0 else "N/A"

        row = [
            r.scheme_name,
            f"{r.keygen_ms:.3f}",
            f"{r.edbsetup_ms:.3f}",
            f"{r.tokengen_ms:.6f}",
            f"{r.search_ms:.6f}",
            edb_overhead,
            search_overhead,
        ]
        print("".join(c.rjust(COL_WIDTH) for c in row))

    print(sep)
    print()

    # ── 详细说明 ──────────────────────────────────────────────────────────────
    print("【性能损失摘要】")
    for r in sse_results:
        edb_ratio = r.edbsetup_ms / pt.build_ms if pt.build_ms > 0 else float("inf")
        search_ratio = r.search_ms / pt.lookup_ms if pt.lookup_ms > 0 else float("inf")
        print(f"  {r.scheme_name}:")
        print(f"    加密建库比明文建库慢 {edb_ratio:.1f}x  "
              f"({r.edbsetup_ms:.2f} ms vs {pt.build_ms:.2f} ms)")
        print(f"    加密搜索比明文查询慢 {search_ratio:.1f}x  "
              f"({r.search_ms:.4f} ms/kw vs {pt.lookup_ms:.6f} ms/kw)")
    print()


# ──────────────────────────────────────────────────────────────────────────────
# JSON 导出
# ──────────────────────────────────────────────────────────────────────────────
def save_results_json(pt: PlaintextResult, sse_results: List[BenchResult],
                       repeat: int, output_dir: str = "benchmark_results") -> str:
    """保存基准测试结果为 JSON 文件"""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(output_dir, f"benchmark_{timestamp}.json")

    data = {
        "metadata": {
            "timestamp": timestamp,
            "repeat": repeat,
            "keyword_count": pt.keyword_count,
            "avg_entries_per_keyword": pt.avg_entries_per_keyword,
            "total_entries": pt.total_entries,
        },
        "plaintext_baseline": pt.to_dict(),
        "sse_schemes": [r.to_dict() for r in sse_results],
        "overhead_analysis": [],
    }

    # 计算性能损失倍数
    for r in sse_results:
        edb_ratio = r.edbsetup_ms / pt.build_ms if pt.build_ms > 0 else float("inf")
        search_ratio = r.search_ms / pt.lookup_ms if pt.lookup_ms > 0 else float("inf")
        data["overhead_analysis"].append({
            "scheme": r.scheme_name,
            "edbsetup_overhead": round(edb_ratio, 2),
            "search_overhead": round(search_ratio, 2),
        })

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return filepath


# ──────────────────────────────────────────────────────────────────────────────
# 可视化图表
# ──────────────────────────────────────────────────────────────────────────────
def plot_results(pt: PlaintextResult, sse_results: List[BenchResult],
                 output_dir: str = "benchmark_results"):
    """绘制性能对比图表"""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    schemes = [r.scheme_name for r in sse_results]
    colors = plt.cm.Set3(range(len(schemes)))

    # ═══════════════════════════════════════════════════════════════════════════
    # 图 1：绝对时间对比（EDBSetup 和 Search）
    # ═══════════════════════════════════════════════════════════════════════════
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # 子图 1：EDBSetup 时间对比（含明文基准）
    edb_times = [pt.build_ms] + [r.edbsetup_ms for r in sse_results]
    labels_edb = [LABELS['plaintext']] + schemes
    colors_edb = ["#90EE90"] + list(colors)

    bars1 = ax1.bar(range(len(labels_edb)), edb_times, color=colors_edb, alpha=0.8)
    ax1.set_xlabel(LABELS['scheme'], fontsize=11)
    ax1.set_ylabel(LABELS['build_time'], fontsize=11)
    ax1.set_title(LABELS['edb_title'], fontsize=13, fontweight='bold')
    ax1.set_xticks(range(len(labels_edb)))
    ax1.set_xticklabels(labels_edb, rotation=15, ha='right')
    ax1.grid(axis='y', alpha=0.3, linestyle='--')

    # 在柱子上标注数值
    for bar in bars1:
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.1f}',
                ha='center', va='bottom', fontsize=9)

    # 子图 2：Search 时间对比（含明文基准）
    search_times = [pt.lookup_ms] + [r.search_ms for r in sse_results]

    bars2 = ax2.bar(range(len(labels_edb)), search_times, color=colors_edb, alpha=0.8)
    ax2.set_xlabel(LABELS['scheme'], fontsize=11)
    ax2.set_ylabel(LABELS['search_time'], fontsize=11)
    ax2.set_title(LABELS['search_title'], fontsize=13, fontweight='bold')
    ax2.set_xticks(range(len(labels_edb)))
    ax2.set_xticklabels(labels_edb, rotation=15, ha='right')
    ax2.grid(axis='y', alpha=0.3, linestyle='--')

    # 在柱子上标注数值
    for bar in bars2:
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.4f}',
                ha='center', va='bottom', fontsize=9)

    plt.tight_layout()
    plot1_path = os.path.join(output_dir, f"time_comparison_{timestamp}.png")
    plt.savefig(plot1_path, dpi=150, bbox_inches='tight')
    print(f"  ✓ 保存图表: {plot1_path}")
    plt.close()

    # ═══════════════════════════════════════════════════════════════════════════
    # 图 2：性能损失倍数（相对于明文基准）
    # ═══════════════════════════════════════════════════════════════════════════
    fig, ax = plt.subplots(figsize=(10, 6))

    edb_overheads = [r.edbsetup_ms / pt.build_ms if pt.build_ms > 0 else 0
                     for r in sse_results]
    search_overheads = [r.search_ms / pt.lookup_ms if pt.lookup_ms > 0 else 0
                        for r in sse_results]

    x = range(len(schemes))
    width = 0.35

    bars1 = ax.bar([i - width/2 for i in x], edb_overheads, width,
                   label=LABELS['build_overhead'], color='#FF9999', alpha=0.8)
    bars2 = ax.bar([i + width/2 for i in x], search_overheads, width,
                   label=LABELS['search_overhead'], color='#66B2FF', alpha=0.8)

    ax.set_xlabel(LABELS['sse_scheme'], fontsize=12)
    ax.set_ylabel(LABELS['overhead_ratio'], fontsize=12)
    ax.set_title(LABELS['overhead_title'], fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(schemes, rotation=15, ha='right')
    ax.legend(fontsize=10)
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.axhline(y=1, color='green', linestyle='--', linewidth=1.5, alpha=0.7,
               label='明文基准 (1x)')

    # 标注倍数
    for bars in [bars1, bars2]:
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{height:.1f}x',
                   ha='center', va='bottom', fontsize=9)

    plt.tight_layout()
    plot2_path = os.path.join(output_dir, f"overhead_comparison_{timestamp}.png")
    plt.savefig(plot2_path, dpi=150, bbox_inches='tight')
    print(f"  ✓ 保存图表: {plot2_path}")
    plt.close()

    # ═══════════════════════════════════════════════════════════════════════════
    # 图 3：各方案操作时间分解（堆叠柱状图）
    # ═══════════════════════════════════════════════════════════════════════════
    fig, ax = plt.subplots(figsize=(10, 6))

    keygen_times = [r.keygen_ms for r in sse_results]
    edb_times_only = [r.edbsetup_ms for r in sse_results]
    tokengen_times = [r.tokengen_ms * r.keyword_count for r in sse_results]  # 总计
    search_times_only = [r.search_ms * r.keyword_count for r in sse_results]  # 总计

    x = range(len(schemes))
    width = 0.6

    p1 = ax.bar(x, keygen_times, width, label='KeyGen', color='#FFD700', alpha=0.9)
    p2 = ax.bar(x, edb_times_only, width, bottom=keygen_times,
               label='EDBSetup', color='#FF6B6B', alpha=0.9)
    p3 = ax.bar(x, tokengen_times, width,
               bottom=[k+e for k, e in zip(keygen_times, edb_times_only)],
               label=LABELS['tokengen_total'], color='#4ECDC4', alpha=0.9)
    p4 = ax.bar(x, search_times_only, width,
               bottom=[k+e+t for k, e, t in zip(keygen_times, edb_times_only, tokengen_times)],
               label=LABELS['search_total'], color='#95E1D3', alpha=0.9)

    ax.set_xlabel(LABELS['sse_scheme'], fontsize=12)
    ax.set_ylabel(LABELS['cumulative_time'], fontsize=12)
    ax.set_title(LABELS['time_breakdown'], fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(schemes, rotation=15, ha='right')
    ax.legend(fontsize=10, loc='upper left')
    ax.grid(axis='y', alpha=0.3, linestyle='--')

    plt.tight_layout()
    plot3_path = os.path.join(output_dir, f"operation_breakdown_{timestamp}.png")
    plt.savefig(plot3_path, dpi=150, bbox_inches='tight')
    print(f"  ✓ 保存图表: {plot3_path}")
    plt.close()


# ──────────────────────────────────────────────────────────────────────────────
# 主函数
# ──────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="SSE 加密性能基准测试")
    parser.add_argument("--keywords", type=int, default=200,
                        help="关键词数量（默认 200）")
    parser.add_argument("--min-entries", type=int, default=5,
                        help="每个关键词最少条目数（默认 5）")
    parser.add_argument("--max-entries", type=int, default=50,
                        help="每个关键词最多条目数（默认 50）")
    parser.add_argument("--repeat", type=int, default=3,
                        help="每项测试重复次数，取平均（默认 3）")
    args = parser.parse_args()

    print(f"\n正在生成测试数据库（{args.keywords} 个关键词，"
          f"每关键词 {args.min_entries}–{args.max_entries} 条）...")
    db = fake_db_for_inverted_index_based_sse(
        KEYWORD_SIZE, FILE_ID_SIZE,
        args.keywords,
        db_w_size_range=(args.min_entries, args.max_entries),
    )
    print(f"数据库生成完毕，共 {sum(len(v) for v in db.values())} 条记录。\n")

    # ── 明文基准 ──────────────────────────────────────────────────────────────
    print("正在运行明文对照测试...")
    pt = run_repeated(lambda: bench_plaintext(db), args.repeat)

    # ── SSE 方案 ──────────────────────────────────────────────────────────────
    schemes_to_bench: List[tuple] = []  # (display_name, module_path)

    # CJJ14.PiBas
    try:
        from schemes.CJJ14.PiBas.construction import PiBas
        from schemes.CJJ14.PiBas.config import DEFAULT_CONFIG as PIBAS_CFG
        schemes_to_bench.append(("CJJ14.PiBas", PiBas, PIBAS_CFG))
        print("已加载方案: CJJ14.PiBas")
    except Exception as e:
        print(f"跳过 CJJ14.PiBas: {e}")

    # CJJ14.Pi2Lev
    try:
        from schemes.CJJ14.Pi2Lev.construction import Pi2Lev
        from schemes.CJJ14.Pi2Lev.config import DEFAULT_CONFIG as PI2LEV_CFG
        schemes_to_bench.append(("CJJ14.Pi2Lev", Pi2Lev, PI2LEV_CFG))
        print("已加载方案: CJJ14.Pi2Lev")
    except Exception as e:
        print(f"跳过 CJJ14.Pi2Lev: {e}")

    # CT14.Pi
    try:
        from schemes.CT14.Pi.construction import Pi as CT14Pi
        from schemes.CT14.Pi.config import DEFAULT_CONFIG as CT14_CFG
        schemes_to_bench.append(("CT14.Pi", CT14Pi, CT14_CFG))
        print("已加载方案: CT14.Pi")
    except Exception as e:
        print(f"跳过 CT14.Pi: {e}")

    # DP17.Pi
    try:
        from schemes.DP17.Pi.construction import Pi as DP17Pi
        from schemes.DP17.Pi.config import DEFAULT_CONFIG as DP17_CFG
        schemes_to_bench.append(("DP17.Pi", DP17Pi, DP17_CFG))
        print("已加载方案: DP17.Pi")
    except Exception as e:
        print(f"跳过 DP17.Pi: {e}")

    # CGKO06.SSE1 (较慢，数据量大时跳过)
    if args.keywords <= 100:
        try:
            from schemes.CGKO06.SSE1.construction import SSE1
            from schemes.CGKO06.SSE1.config import DEFAULT_CONFIG as SSE1_CFG
            schemes_to_bench.append(("CGKO06.SSE1", SSE1, SSE1_CFG))
            print("已加载方案: CGKO06.SSE1")
        except Exception as e:
            print(f"跳过 CGKO06.SSE1: {e}")
    else:
        print(f"CGKO06.SSE1 在关键词 > 100 时跳过（速度较慢）")

    print()
    sse_results: List[BenchResult] = []
    for display_name, SchemeClass, cfg in schemes_to_bench:
        print(f"正在测试 {display_name}（重复 {args.repeat} 次）...")
        try:
            result = run_repeated(
                lambda sc=SchemeClass, c=cfg: bench_scheme(display_name, sc, c, db),
                args.repeat,
            )
            sse_results.append(result)
        except Exception as e:
            print(f"  测试失败: {e}")

    if not sse_results:
        print("没有成功测试的 SSE 方案，退出。")
        return

    print_results(pt, sse_results, args.repeat)

    # ── 保存 JSON 和绘制图表 ──────────────────────────────────────────────────
    print("\n正在保存结果...")
    json_path = save_results_json(pt, sse_results, args.repeat)
    print(f"  ✓ JSON 结果已保存至: {json_path}")

    print("\n正在生成可视化图表...")
    plot_results(pt, sse_results)
    print("\n所有结果已保存至 benchmark_results/ 目录")


if __name__ == "__main__":
    main()
