# -*- coding: utf-8 -*-
"""
Criteo数据集加密测试脚本
========================
用于测试Criteo搜索转化数据集的加密性能。

数据集格式（TSV，制表符分隔）：
  Sale, SalesAmountInEuro, time_delay_for_conversion, click_timestamp, 
  nb_clicks_1week, product_price, product_age_group, device_type, 
  audience_id, product_gender, product_brand, product_category(1-7), 
  product_country, product_id, product_title, partner_id, user_id

用法:
    python test_dataset_encryption.py --file CriteoSearchData/Criteo_Conversion_Search.tsv --limit 10000
    python test_dataset_encryption.py --file dataset.tsv --limit 50000 --scheme CJJ14.PiBas
"""

import argparse
import gzip
import hashlib
import importlib
import json
import os
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List
import multiprocessing


@dataclass
class EncryptionBenchmark:
    """加密性能测试结果"""
    scheme_name: str
    dataset_file: str
    total_records: int
    unique_keywords: int
    total_keyword_value_pairs: int
    
    # 时间测量（秒）
    data_loading_time: float = 0.0
    index_building_time: float = 0.0
    keygen_time: float = 0.0
    edb_setup_time: float = 0.0
    total_time: float = 0.0
    
    # 内存占用（字节）
    plaintext_db_size: int = 0
    encrypted_db_size: int = 0
    
    timestamp: str = ""

    def to_dict(self):
        return asdict(self)


class CriteoDatasetProcessor:
    """Criteo数据集处理器"""

    FIELD_NAMES = [
        'Sale',
        'SalesAmountInEuro',
        'time_delay_for_conversion',
        'click_timestamp',
        'nb_clicks_1week',
        'product_price',
        'product_age_group',
        'device_type',
        'audience_id',
        'product_gender',
        'product_brand',
        'product_category_1',
        'product_category_2',
        'product_category_3',
        'product_category_4',
        'product_category_5',
        'product_category_6',
        'product_category_7',
        'product_country',
        'product_id',
        'product_title',
        'partner_id',
        'user_id',
    ]
    
    # 可以用作搜索关键字的字段（分类字段）
    SEARCHABLE_FIELDS = [
        'product_brand',
        'product_country', 
        'product_gender',
        'product_age_group',
        'device_type',
        'product_category_1',
        'product_category_2',
        'product_category_3',
        'product_category_4',
        'product_category_5',
        'product_category_6',
        'product_category_7',
    ]
    
    def __init__(self, file_path: str, batchsize: int = 100000):
        self.file_path = file_path
        self.batchsize = batchsize
        self.inverted_index = defaultdict(set)
        self.batch_count = 0
        self.total_batches_encrypted = 0
        
    def load_data(self, max_records: int = None, callback_batch_full=None) -> int:
        """
        加载TSV数据集（流式）
        
        Args:
            max_records: 最大加载记录数，None表示全部加载
            callback_batch_full: 当索引达到batchsize时的回调函数，参数为当前索引
            
        Returns:
            加载的记录数
        """
        print(f"📂 加载数据集: {self.file_path}")
        
        # 判断是否是gzip压缩文件
        is_gzip = self.file_path.endswith('.gz')

        try:
            if is_gzip:
                file_handle = gzip.open(self.file_path, 'rt', encoding='utf-8', errors='replace')
            else:
                file_handle = open(self.file_path, 'r', encoding='utf-8', errors='replace')

            count = 0
            skipped_count = 0
            for line in file_handle:
                record = self._parse_line_to_record(line)
                if record is None:
                    skipped_count += 1
                    continue

                self._index_record(count, record)
                count += 1
                
                # 检查索引是否达到 batchsize
                if len(self.inverted_index) >= self.batchsize and callback_batch_full:
                    print(f"  索引达到 {self.batchsize} 词阈值，触发批处理回调...")
                    callback_batch_full(self.get_and_reset_index())
                    self.total_batches_encrypted += 1

                if max_records and count >= max_records:
                    break

                if count % 10000 == 0:
                    print(f"  已加载 {count} 条记录...")

            file_handle.close()

            print(f"✓ 成功加载 {count} 条记录")
            if skipped_count > 0:
                print(f"  - 跳过异常/空行: {skipped_count}")
            return count

        except FileNotFoundError:
            print(f"✗ 错误：文件不存在 - {self.file_path}")
            return 0
        except Exception as e:
            print(f"✗ 加载数据时出错: {e}")
            return 0

    def _parse_line_to_record(self, line: str):
        """将一行文本解析为记录字典。支持制表符和空白分隔。"""
        line = line.strip()
        if not line:
            return None

        if '\t' in line:
            parts = [item.strip() for item in line.split('\t') if item.strip() != '']
        else:
            parts = line.split()

        if not parts:
            return None

        first_token = parts[0].lower()
        if first_token in {'sale', '<sale>'}:
            return None

        expected_len = len(self.FIELD_NAMES)
        if len(parts) < expected_len:
            return None
        if len(parts) > expected_len:
            parts = parts[:expected_len]

        return dict(zip(self.FIELD_NAMES, parts))

    def _index_record(self, idx: int, record: dict):
        """在读取记录时增量构建倒排索引，避免全量缓存。"""
        record_id = self._generate_record_id(idx, record)

        for field in self.SEARCHABLE_FIELDS:
            value = record.get(field, '').strip()
            if value and value != '-1' and value != '0':
                keyword = f"{field}:{value}".encode('utf-8')
                self.inverted_index[keyword].add(record_id)
    
    def get_and_reset_index(self) -> Dict[bytes, List[bytes]]:
        """获取当前索引并重置，用于分批处理"""
        inverted_index_dict = {
            kw: list(ids) for kw, ids in self.inverted_index.items()
        }
        self.inverted_index.clear()
        self.batch_count += 1
        return inverted_index_dict
    
    def build_inverted_index(self) -> Dict[bytes, List[bytes]]:
        """
        汇总当前积累的倒排索引
        
        格式: {keyword: [record_id1, record_id2, ...]}
        record_id 使用记录内容的hash值
        
        Returns:
            倒排索引字典
        """
        if len(self.inverted_index) > 0:
            print(f"🔨 汇总最后一批索引...")
        else:
            print(f"🔨 索引汇总...")
        
        # 转换为列表格式
        inverted_index_dict = {
            kw: list(ids) for kw, ids in self.inverted_index.items()
        }
        
        total_pairs = sum(len(ids) for ids in inverted_index_dict.values())
        avg_pairs = (total_pairs / len(inverted_index_dict)) if inverted_index_dict else 0.0

        print(f"✓ 索引汇总完成:")
        print(f"  - 唯一关键字数: {len(inverted_index_dict)}")
        print(f"  - 关键字-值对数: {total_pairs}")
        print(f"  - 平均每个关键字的值数: {avg_pairs:.2f}")
        if self.total_batches_encrypted > 0:
            print(f"  - 已处理的批数: {self.total_batches_encrypted}")
        
        return inverted_index_dict
    
    def _generate_record_id(self, idx: int, record: dict) -> bytes:
        """生成记录ID"""
        # 使用行号和部分关键字段生成唯一ID
        id_str = f"{idx}_{record.get('user_id', '')}_{record.get('click_timestamp', '')}"
        return hashlib.sha256(id_str.encode()).digest()[:16]  # 16字节


def _encrypt_batch_worker(scheme_name: str, inverted_index: Dict[bytes, List[bytes]], batch_id: int):
    """
    多进程/多线程工作函数（加密单个批次）
    
    Args:
        scheme_name: 加密方案名称
        inverted_index: 该批的倒排索引
        batch_id: 批次编号
        
    Returns:
        (batch_id, keywords_count, keygen_time, edb_setup_time)
    """
    tester = SSEEncryptionTester(scheme_name)
    if not tester.load_scheme():
        return (batch_id, 0, 0, 0)
    
    key, edb, keygen_time, edb_setup_time = tester.test_encryption_silent(inverted_index)
    return (batch_id, len(inverted_index), keygen_time, edb_setup_time)


class SSEEncryptionTester:
    """SSE加密测试器"""
    
    def __init__(self, scheme_name: str = "CJJ14.PiBas"):
        self.scheme_name = scheme_name
        self.scheme_module = None
        self.config_dict = None
        self.sse_class = None
        
    def load_scheme(self):
        """动态加载SSE方案"""
        print(f"🔐 加载SSE方案: {self.scheme_name}")
        
        try:
            # 解析方案名称
            parts = self.scheme_name.split('.')
            if len(parts) != 2:
                raise ValueError(f"方案名称格式错误: {self.scheme_name}，应为'CJJ14.PiBas'格式")
            
            scheme_family, scheme_variant = parts
            
            # 动态导入
            config_module = importlib.import_module(
                f'schemes.{scheme_family}.{scheme_variant}.config'
            )
            sse_module = importlib.import_module(
                f'schemes.{scheme_family}.{scheme_variant}.construction'
            )

            if not hasattr(config_module, 'DEFAULT_CONFIG'):
                raise AttributeError(
                    f"module 'schemes.{scheme_family}.{scheme_variant}.config' has no attribute 'DEFAULT_CONFIG'"
                )
            if not hasattr(sse_module, scheme_variant):
                raise AttributeError(
                    f"module 'schemes.{scheme_family}.{scheme_variant}.construction' has no attribute '{scheme_variant}'"
                )

            self.config_dict = config_module.DEFAULT_CONFIG
            self.sse_class = getattr(sse_module, scheme_variant)
            
            print(f"✓ 方案加载成功")
            return True
            
        except Exception as e:
            print(f"✗ 加载方案失败: {e}")
            return False
    
    def test_encryption(self, inverted_index: Dict[bytes, List[bytes]]) -> tuple:
        """
        测试加密过程
        
        Args:
            inverted_index: 倒排索引
            
        Returns:
            (key, edb, keygen_time, edb_setup_time)
        """
        print(f"⚡ 开始加密测试...")
        
        # 初始化SSE实例
        sse = self.sse_class(self.config_dict)
        
        # 1. 密钥生成
        print(f"  1) 密钥生成 (KeyGen)...")
        start_time = time.time()
        key = sse.KeyGen()
        keygen_time = time.time() - start_time
        print(f"     耗时: {keygen_time * 1000:.2f} ms")
        
        # 2. 加密数据库建立
        print(f"  2) 加密数据库建立 (EDBSetup)...")
        start_time = time.time()
        edb = sse.EDBSetup(key, inverted_index)
        edb_setup_time = time.time() - start_time
        print(f"     耗时: {edb_setup_time * 1000:.2f} ms ({edb_setup_time:.2f} s)")
        
        return key, edb, keygen_time, edb_setup_time
    
    def test_encryption_silent(self, inverted_index: Dict[bytes, List[bytes]]) -> tuple:
        """
        无输出的加密测试（用于多进程）
        
        Args:
            inverted_index: 倒排索引
            
        Returns:
            (key, edb, keygen_time, edb_setup_time)
        """
        # 初始化SSE实例
        sse = self.sse_class(self.config_dict)
        
        # 1. 密钥生成
        start_time = time.time()
        key = sse.KeyGen()
        keygen_time = time.time() - start_time
        
        # 2. 加密数据库建立
        start_time = time.time()
        edb = sse.EDBSetup(key, inverted_index)
        edb_setup_time = time.time() - start_time
        
        return key, edb, keygen_time, edb_setup_time
    
    def estimate_size(self, obj) -> int:
        """估算对象大小（字节）"""
        try:
            import pickle
            return len(pickle.dumps(obj))
        except:
            return 0


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='Criteo数据集加密性能测试',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python test_dataset_encryption.py --file dataset.tsv                   # 加载全部数据
  python test_dataset_encryption.py --file data.tsv --limit 50000        # 加载前50000条
  python test_dataset_encryption.py --file data.tsv --batchsize 50000    # 设置批大小
        """
    )
    
    parser.add_argument(
        '--file', '-f',
        type=str,
        default='CriteoSearchData/Criteo_Conversion_Search.tsv',
        help='数据集文件路径（支持.tsv和.tsv.gz）'
    )
    
    parser.add_argument(
        '--limit', '-l',
        type=int,
        default=None,
        help='最大加载记录数（默认: None，加载全部数据）'
    )
    
    parser.add_argument(
        '--batchsize', '-b',
        type=int,
        default=100000,
        help='内存中保留的倒排索引最大词数，超过此限制将分批处理（默认: 100000）'
    )
    
    parser.add_argument(
        '--scheme', '-s',
        type=str,
        default='CJJ14.PiBas',
        choices=['CJJ14.PiBas', 'CJJ14.Pi2Lev', 'CJJ14.PiPack', 'CJJ14.PiPtr', 'CT14.Pi', 'DP17.Pi'],
        help='SSE加密方案（默认: CJJ14.PiBas）'
    )
    
    parser.add_argument(
        '--workers', '-w',
        type=int,
        default=multiprocessing.cpu_count(),
        help=f'并行工作线程数（默认: {multiprocessing.cpu_count()} 核）'
    )
    
    parser.add_argument(
        '--output', '-o',
        type=str,
        default='dataset_encryption_results',
        help='结果输出目录（默认: dataset_encryption_results）'
    )
    
    return parser.parse_args()


def format_time(seconds: float) -> str:
    """格式化时间显示"""
    if seconds < 1:
        return f"{seconds * 1000:.2f} ms"
    elif seconds < 60:
        return f"{seconds:.2f} s"
    else:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.2f}s"


def format_size(bytes_size: int) -> str:
    """格式化大小显示"""
    if bytes_size < 1024:
        return f"{bytes_size} B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.2f} KB"
    elif bytes_size < 1024 * 1024 * 1024:
        return f"{bytes_size / (1024 * 1024):.2f} MB"
    else:
        return f"{bytes_size / (1024 * 1024 * 1024):.2f} GB"


def main():
    args = parse_args()
    
    print("=" * 70)
    print("Criteo数据集加密性能测试")
    print("=" * 70)
    print(f"数据集文件: {args.file}")
    print(f"记录数限制: {args.limit if args.limit else '无限制（全部）'}")
    print(f"批处理大小: {args.batchsize} 词/批")
    print(f"加密方案: {args.scheme}")
    print(f"并行工作线程数: {args.workers}")
    print("=" * 70)
    print()
    
    # 创建结果对象
    benchmark = EncryptionBenchmark(
        scheme_name=args.scheme,
        dataset_file=args.file,
        total_records=0,
        unique_keywords=0,
        total_keyword_value_pairs=0,
        timestamp=datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    
    total_start = time.time()
    
    # 1. 加载数据（流式）
    print("【步骤 1/4】数据加载与索引构建（流式）")
    print("-" * 70)
    processor = CriteoDatasetProcessor(args.file, batchsize=args.batchsize)
    
    print("【步骤 2/4】加载加密方案")
    print("-" * 70)
    tester = SSEEncryptionTester(args.scheme)
    if not tester.load_scheme():
        print("✗ 加载方案失败，退出")
        return
    print()
    print(f"🔄 并行工作线程数: {args.workers}")
    print()
    
    # 定义批处理回调（只收集批数据，不立即处理）
    batch_indices = []  # 存储所有批的倒排索引
    def collect_batch(batch_index):
        batch_indices.append(batch_index)
        print(f"  > 第 {len(batch_indices)} 批索引已收集 ({len(batch_index)} 词)")
    
    # 加载数据，触发流式索引构建
    load_start = time.time()
    records_count = processor.load_data(max_records=args.limit, callback_batch_full=collect_batch)
    benchmark.data_loading_time = time.time() - load_start
    benchmark.total_records = records_count
    
    if records_count == 0:
        print("✗ 没有加载任何数据，退出")
        return
    
    print()
    
    # 2. 用线程池并行加密所有批
    print("【步骤 3/4】并行加密批次")
    print("-" * 70)
    
    batch_results = []
    encrypt_start = time.time()
    
    # 准备任务数据
    batch_tasks = [
        (args.scheme, batch_indices[i], i)
        for i in range(len(batch_indices))
    ]
    
    if batch_indices:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(_encrypt_batch_worker, scheme, idx, batch_id): batch_id
                for scheme, idx, batch_id in batch_tasks
            }
            
            for future in as_completed(futures):
                batch_id, keywords_count, keygen_time, edb_setup_time = future.result()
                batch_results.append({
                    'batch_id': batch_id,
                    'keywords': keywords_count,
                    'keygen_time': keygen_time,
                    'edb_setup_time': edb_setup_time
                })
                print(f"  ✓ 批 {batch_id+1} 加密完成 ({keywords_count} 词, {format_time(keygen_time+edb_setup_time)})")
        
        # 按批次ID排序
        batch_results.sort(key=lambda x: x['batch_id'])
    
    total_encrypt_time = time.time() - encrypt_start
    
    print()
    
    # 4. 处理最后一批未达到 batchsize 的索引
    print("【步骤 4/4】处理剩余索引")
    print("-" * 70)
    
    index_start = time.time()
    inverted_index = processor.build_inverted_index()
    benchmark.index_building_time = time.time() - index_start
    
    # 处理最后一批（如果有剩余）
    if len(inverted_index) > 0:
        print(f"  > 处理最后一批索引 ({len(inverted_index)} 词)...")
        batch_id = len(batch_results)
        key, edb, keygen_time, edb_setup_time = tester.test_encryption(inverted_index)
        batch_results.append({
            'batch_id': batch_id,
            'keywords': len(inverted_index),
            'keygen_time': keygen_time,
            'edb_setup_time': edb_setup_time
        })
        print(f"  ✓ 最后一批加密完成 ({format_time(keygen_time+edb_setup_time)})")
        total_encrypt_time += (keygen_time + edb_setup_time)
    
    benchmark.unique_keywords = sum(b['keywords'] for b in batch_results) if batch_results else 0
    benchmark.total_keyword_value_pairs = benchmark.unique_keywords
    benchmark.plaintext_db_size = sum(
        (len(k) if isinstance(k, (bytes, bytearray)) else len(str(k).encode('utf-8'))) +
        sum(len(v) for v in vals)
        for k, vals in inverted_index.items()
    )
    
    # 计算汇总时间
    total_keygen = sum(b['keygen_time'] for b in batch_results) if batch_results else 0
    total_edb_setup = sum(b['edb_setup_time'] for b in batch_results) if batch_results else 0
    benchmark.keygen_time = total_keygen
    benchmark.edb_setup_time = total_edb_setup
    benchmark.encrypted_db_size = 0  # 分批加密时，不计算总大小
    
    benchmark.total_time = time.time() - total_start
    
    print()
    print("=" * 70)
    print("测试完成！")
    print("=" * 70)
    
    # 打印结果摘要
    print("\n📊 性能测试结果摘要:")
    print("-" * 70)
    print(f"数据集信息:")
    print(f"  - 总记录数:           {benchmark.total_records:,}")
    print(f"  - 总关键字数:         {benchmark.unique_keywords:,}")
    
    # 批处理信息
    if len(batch_results) > 1:
        print(f"\n⚙️  并行加密信息:")
        print(f"  - 批次数:             {len(batch_results)}")
        print(f"  - 工作线程数:         {args.workers}")
        for i, batch in enumerate(batch_results):
            print(f"    批 {batch['batch_id']+1}: {batch['keywords']:6d} 词  KeyGen={format_time(batch['keygen_time']):10s}  Setup={format_time(batch['edb_setup_time']):10s}")
        
        # 计算理论加速比
        total_sequential = sum(b['keygen_time'] + b['edb_setup_time'] for b in batch_results)
        print(f"  - 总加密时间（顺序）: {format_time(total_sequential)}")
        print(f"  - 总加密时间（并行）: {format_time(benchmark.edb_setup_time + benchmark.keygen_time)}")
        if total_sequential > 0:
            speedup = total_sequential / (benchmark.edb_setup_time + benchmark.keygen_time)
            print(f"  - 加速比:             {speedup:.2f}x")
    
    print()
    print(f"时间性能:")
    print(f"  - 数据加载:           {format_time(benchmark.data_loading_time)}")
    print(f"  - 索引构建:           {format_time(benchmark.index_building_time)}")
    print(f"  - 密钥生成 (KeyGen)  总计: {format_time(benchmark.keygen_time)}")
    print(f"  - 加密建库 (Setup)   总计: {format_time(benchmark.edb_setup_time)}")
    print(f"  - 总耗时:             {format_time(benchmark.total_time)}")
    print()
    
    # 保存结果到文件
    os.makedirs(args.output, exist_ok=True)
    result_file = os.path.join(
        args.output,
        f"encryption_test_{args.scheme.replace('.', '_')}_{benchmark.timestamp}.json"
    )
    
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(benchmark.to_dict(), f, indent=2, ensure_ascii=False)
    
    print(f"✓ 结果已保存到: {result_file}")
    print()


if __name__ == "__main__":
    main()
