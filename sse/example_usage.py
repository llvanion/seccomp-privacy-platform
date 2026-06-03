# -*- coding:utf-8 -*-
"""
示例用法：多key索引检索、删除数据、更新数据
============================================

多key检索说明：
  同一段数据可以设置多个检索key，使用其中任意一个key检索都会返回那段数据。
  例如：数据 ["3A4B1ACC"] 绑定了 "China"、"中国"、"CN" 三个key，
  搜索 "China" 或 "中国" 或 "CN" 都能找到 ["3A4B1ACC"]。

运行前须先启动服务器：
    python run_server.py start

然后执行本示例：
    python example_usage.py
"""

import asyncio
import itertools

from frontend.common.wire import decode_content
from frontend.client.services.service import Service, ClientServiceState


# ============================================================
# 示例 1：多key索引检索 —— 核心功能演示
# ============================================================
async def example_multi_key_search():
    """
    多key索引检索：同一组数据绑定多个keyword，搜索任意一个keyword即可命中。

    数据库格式（多key索引格式）:
        [
            {"keys": ["China", "中国", "CN"], "values": ["3A4B1ACC12AA1B2D", "2DDD1FFF1122BBCC"]},
            {"keys": ["Github", "代码托管"],   "values": ["1A1ADD2C2320A1CC"]},
            {"keys": ["Chen", "陈"],          "values": ["1BB2BB2B1010112A", "88771ABB101AA02B"]}
        ]

    加密后，搜索 "China" 或 "中国" 或 "CN" 都能返回 [3A4B1ACC12AA1B2D, 2DDD1FFF1122BBCC]。
    """
    from schemes.CJJ14.PiBas.config import DEFAULT_CONFIG as PI_BAS_DEFAULT_CONFIG

    print("=" * 60)
    print("示例 1：多key索引检索")
    print("=" * 60)

    # ---- 多key索引格式的数据库 ----
    multi_key_db = [
        {
            "keys": ["China", "中国", "CN"],
            "values": ["3A4B1ACC12AA1B2D", "2DDD1FFF1122BBCC"]
        },
        {
            "keys": ["Github", "代码托管"],
            "values": ["1A1ADD2C2320A1CC", "2222CC1F1421A22A"]
        },
        {
            "keys": ["Chen", "陈"],
            "values": ["1BB2BB2B1010112A", "233278781010212C", "88771ABB101AA02B"]
        }
    ]

    # 1. 创建服务
    service = Service()
    service.handle_create_config(PI_BAS_DEFAULT_CONFIG)
    service.handle_create_key()

    # 2. 使用多key索引方式加密数据库
    #    内部会把多key格式展开成标准倒排索引再加密
    service.handle_encrypt_database_multi_key(multi_key_db)

    # 3. 上传
    await service.handle_upload_config(wait=True)
    while not ClientServiceState.is_config_uploaded(service.get_current_service_state()):
        await asyncio.sleep(0.5)
    await service.handle_upload_encrypted_database(wait=True)
    while not ClientServiceState.is_db_uploaded(service.get_current_service_state()):
        await asyncio.sleep(0.5)

    # 4. 用不同的key搜索同一组数据 —— 都应该命中
    test_keys = ["China", "中国", "CN"]
    print(f"\n>>> 数据 [3A4B1ACC12AA1B2D, 2DDD1FFF1122BBCC] 绑定了 keys: {test_keys}")
    print(f">>> 用任意一个key搜索，应该都能找到该数据：\n")

    def search_callback(keyword_name):
        def callback(fut: asyncio.Future):
            result_bytes = fut.result()
            result_obj = service.sse_module_loader.SSEResult.deserialize(result_bytes, service.config_object)
            result_list = result_obj.get_result_list()
            print(f"    → 找到 {len(result_list)} 条结果: {[r.hex() for r in result_list]}")
        return callback

    for kw in test_keys:
        kw_bytes = kw.encode("utf-8")
        print(f"  搜索 \"{kw}\" ...")
        await service.handle_keyword_search(kw_bytes, wait=True, wait_callback_func=search_callback(kw))

    # 搜索另一组
    print(f"\n>>> 数据 [1A1ADD2C2320A1CC, 2222CC1F1421A22A] 绑定了 keys: ['Github', '代码托管']")
    for kw in ["Github", "代码托管"]:
        kw_bytes = kw.encode("utf-8")
        print(f"  搜索 \"{kw}\" ...")
        await service.handle_keyword_search(kw_bytes, wait=True, wait_callback_func=search_callback(kw))

    await service.close_service()
    print("\n>>> 示例 1 完成\n")
    return service.sid


# ============================================================
# 示例 2：基础流程 + 单keyword检索
# ============================================================
async def example_single_search():
    """基础示例：创建服务 → 上传配置 → 加密数据库 → 上传 → 单keyword检索"""
    from schemes.CJJ14.PiBas.config import DEFAULT_CONFIG as PI_BAS_DEFAULT_CONFIG
    from test.tools.faker import fake_db_for_inverted_index_based_sse
    from test.test_sse_schemes.test_CJJ14_PiBas import TEST_KEYWORD_SIZE, TEST_FILE_ID_SIZE

    print("=" * 60)
    print("示例 2：单keyword检索")
    print("=" * 60)

    db = fake_db_for_inverted_index_based_sse(
        TEST_KEYWORD_SIZE, TEST_FILE_ID_SIZE,
        100, db_w_size_range=(1, 20)
    )

    service = Service()
    service.handle_create_config(PI_BAS_DEFAULT_CONFIG)
    service.handle_create_key()
    service.handle_encrypt_database(db)

    await service.handle_upload_config(wait=True)
    while not ClientServiceState.is_config_uploaded(service.get_current_service_state()):
        await asyncio.sleep(0.5)

    await service.handle_upload_encrypted_database(wait=True)
    while not ClientServiceState.is_db_uploaded(service.get_current_service_state()):
        await asyncio.sleep(0.5)

    def search_callback(fut: asyncio.Future):
        result_bytes = fut.result()
        result_obj = service.sse_module_loader.SSEResult.deserialize(result_bytes, service.config_object)
        result_list = result_obj.get_result_list()
        print(f"    → 找到 {len(result_list)} 条结果: {[r.hex() for r in result_list]}")

    keywords = list(itertools.islice(db.keys(), 3))
    for keyword in keywords:
        print(f"\n>>> 正在检索 keyword (hex): {keyword.hex()[:16]}...")
        await service.handle_keyword_search(keyword, wait=True, wait_callback_func=search_callback)

    await service.close_service()
    print("\n>>> 示例 2 完成\n")
    return service.sid, db


# ============================================================
# 示例 3：删除数据
# ============================================================
async def example_delete(sid: str, db: dict):
    """删除数据示例：通过keyword的token删除对应的加密数据"""
    print("=" * 60)
    print("示例 3：删除数据")
    print("=" * 60)

    await asyncio.sleep(1.1)
    service = Service(sid)

    keyword = next(iter(db.keys()))
    print(f">>> 正在删除 keyword (hex): {keyword.hex()[:16]}...")

    def delete_callback(fut: asyncio.Future):
        content = decode_content(fut.result())
        if not content.get("ok", False):
            reason = content.get("reason", "")
            print(f">>> 删除结果: {reason}")
            return
        deleted_count = content.get("deleted_count", 0)
        print(f">>> 删除成功: 删除了 {deleted_count} 条数据")

    await service.handle_delete(
        keyword=keyword,
        wait=True,
        wait_callback_func=delete_callback
    )

    await service.close_service()
    print("\n>>> 示例 3 完成\n")


# ============================================================
# 示例 4：更新数据
# ============================================================
async def example_update(sid: str, db: dict):
    """更新数据示例：通过keyword的token更新对应的加密数据"""
    print("=" * 60)
    print("示例 4：更新数据")
    print("=" * 60)

    await asyncio.sleep(1.1)
    service = Service(sid)

    keyword = next(iter(db.keys()))
    print(f">>> 正在更新 keyword (hex): {keyword.hex()[:16]}...")

    def update_callback(fut: asyncio.Future):
        content = decode_content(fut.result())
        if not content.get("ok", False):
            reason = content.get("reason", "")
            print(f">>> 更新结果: {reason}")
            return
        updated_count = content.get("updated_count", 0)
        print(f">>> 更新成功: 更新了 {updated_count} 条数据")

    await service.handle_update(
        keyword=keyword,
        encrypted_data=b"new_encrypted_data_placeholder",
        wait=True,
        wait_callback_func=update_callback
    )

    await service.close_service()
    print("\n>>> 示例 4 完成\n")


# ============================================================
# 主函数
# ============================================================
async def main():
    """
    运行所有示例。

    示例 1：多key索引检索（核心新功能）
      - 同一段数据绑定多个keyword
      - 搜索任意一个keyword都会命中该数据
    示例 2：基础流程 + 单keyword检索
    示例 3：删除数据
    示例 4：更新数据

    毫秒级时间日志在 ~/.sse/log/ 中查看。
    """
    print("SSEPy 扩展功能示例")
    print("功能：多key索引检索 | 删除数据 | 更新数据 | 毫秒级时间日志")
    print("=" * 60)
    print()

    # 示例 1：多key索引检索（核心功能）
    await example_multi_key_search()

    # 示例 2：基础流程 + 单keyword检索
    sid, db = await example_single_search()

    # 示例 3：删除数据
    await example_delete(sid, db)

    # 示例 4：更新数据
    await example_update(sid, db)

    print("=" * 60)
    print("所有示例已完成！")
    print("查看 ~/.sse/log/ 目录下的日志文件可看到毫秒级加解密时间。")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
