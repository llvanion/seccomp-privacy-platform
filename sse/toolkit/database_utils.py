# -*- coding:utf-8 _*-
""" 
LIB-SSE CODE
@author: Jeza Chen
@license: GPL-3.0 License 
@file: database_utils.py 
@time: 2022/03/11
@contact: jeza@vip.qq.com
@site:  
@software: PyCharm 
@description:
Database related utility functions,
such as getting the number of individual keywords, database size, etc.
"""


def get_total_size(db: dict):
    """Get the total size of the database N"""
    return sum(len(identifier_list) for identifier_list in db.values())


def get_distinct_keyword_count(db: dict):
    """Get the number of distinct keywords in the database"""
    return len(db)


def get_distinct_file_count(db: dict):
    """Get the number of distinct file identifiers in the database"""
    file_set = set()
    for identifier_list in db.values():
        file_set.update(identifier_list)
    return len(file_set)


def partition_identifiers_to_blocks(identifier_list: list,
                                    entry_count_in_one_block: int,
                                    identifier_size: int,
                                    block_size_bytes: int = 0):
    """
    Store multiple file identifiers in blocks, where each block is a byte string.
    :param identifier_list: A list of file identifiers
    :param entry_count_in_one_block: Number of file identifiers contained on a block
    :param identifier_size: Size of the file identifier, in bytes
    :param block_size_bytes: Size of the block, in bytes
    :return:
    todo use toolkit.list_utils.chunks method
    """
    if block_size_bytes == 0:
        block_size_bytes = entry_count_in_one_block * identifier_size

    if block_size_bytes < entry_count_in_one_block * identifier_size:
        raise ValueError(
            "parameter block_size_bytes should be greater than or equal to "
            "entry_count_in_one_block * identifier_size")

    for i in range(0, len(identifier_list), entry_count_in_one_block):
        block = b''.join(identifier_list[i:i + entry_count_in_one_block])
        if len(block) < block_size_bytes:
            block += b'\x00' * (block_size_bytes - len(block))
        yield block


def parse_identifiers_from_block_given_identifier_size(block: bytes,
                                                       identifier_size: int):
    """Parses a list of file identifiers from a block, given the file identifier size."""
    result = []
    for i in range(0, len(block), identifier_size):
        identifier = block[i:i + identifier_size]
        if identifier == b'\x00' * len(identifier):
            break
        result.append(identifier)
    return result


def parse_identifiers_from_block_given_entry_count_in_one_block(
        block: bytes, entry_count_in_one_block: int):
    """Parses a list of file identifiers from a block, given the number of file identifiers in the block."""
    identifier_size = len(block) // entry_count_in_one_block
    return parse_identifiers_from_block_given_identifier_size(
        block, identifier_size)


def convert_database_keyword_to_bytes(db: dict, encoding="utf-8"):
    """Make sure that all keywords in db are strings and all values are hex-strings. """
    result = {}
    for keyword in db:
        keyword_bytes = bytes(keyword, encoding=encoding)
        identifier_bytes_list = []
        for identifier in db[keyword]:
            identifier_bytes_list.append(bytes.fromhex(identifier))
        result[keyword_bytes] = identifier_bytes_list
    return result


def convert_multi_key_database(multi_key_db: list, encoding="utf-8") -> dict:
    """
    将多key索引格式的数据库转换为标准倒排索引格式。

    多key格式：同一组数据可绑定多个keyword，搜索任意一个keyword都能找到该组数据。

    输入格式（list of entries）:
        [
            {
                "keys": ["keyword1", "keyword2", ...],
                "values": ["hex_id1", "hex_id2", ...]
            },
            ...
        ]

    输出格式（标准倒排索引 dict）:
        {
            b"keyword1": [b"id1", b"id2"],
            b"keyword2": [b"id1", b"id2"],
            ...
        }

    每条数据的 values 会在其所有 keys 下各建一份索引。
    """
    result = {}
    for entry in multi_key_db:
        keys = entry.get("keys", [])
        values = entry.get("values", [])
        identifier_bytes_list = [bytes.fromhex(v) for v in values]
        for keyword in keys:
            keyword_bytes = bytes(keyword, encoding=encoding) if isinstance(keyword, str) else keyword
            if keyword_bytes not in result:
                result[keyword_bytes] = []
            result[keyword_bytes].extend(identifier_bytes_list)
    return result


def convert_multi_key_database_from_file(file_path: str, encoding="utf-8") -> dict:
    """
    从JSON文件加载多key索引格式数据库并转换。

    JSON文件格式:
        [
            {"keys": ["k1", "k2"], "values": ["AA11BB22", "CC33DD44"]},
            {"keys": ["k3"],       "values": ["EE55FF66"]}
        ]

    返回标准倒排索引 dict（bytes key -> list of bytes values）。
    """
    import json
    with open(file_path, "r", encoding=encoding) as f:
        multi_key_db = json.load(f)
    return convert_multi_key_database(multi_key_db, encoding=encoding)


if __name__ == '__main__':
    test_db = {
        b"a": [1, 2, 3, 4, 6],
        b"b": [1, 4, 5, 6, 7],
        b"c": [1, 2, 3, 9, 11]
    }
    print(get_total_size(test_db))
    print(get_distinct_keyword_count(test_db))
    print(get_distinct_file_count(test_db))
