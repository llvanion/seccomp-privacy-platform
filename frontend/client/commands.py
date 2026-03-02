# -*- coding:utf-8 _*-
""" 
LIB-SSE CODE
@author: Jeza Chen
@license: GPL-3.0 License
@file: commands.py 
@time: 2022/03/18
@contact: jeza@vip.qq.com
@site:  
@software: PyCharm 
@description: Non-interactive command processing module
This module needs to be responsible for processing commands
and converting data structures into structures that the service can understand
@todo need to wrap service
"""
import asyncio
import functools
import json
import pickle

import schemes
from frontend.client.services import service_name_handler
from frontend.client.services.service import Service
from toolkit.bytes_utils import BytesConverter
from toolkit.config_manager import write_config, read_config
from toolkit.database_utils import convert_database_keyword_to_bytes

__client_service = None


def generate_default_config(scheme_name: str, config_save_path: str):
    try:
        sse_module_loader = schemes.load_sse_module(scheme_name)
    except ValueError:
        print(f">>> Unsupported SSE Scheme {scheme_name}.")
        return

    default_config = sse_module_loader.SSEConfig.get_default_config()
    write_config(default_config, config_save_path)
    print(f">>> Create default config of {scheme_name} successfully.")


def create_service(config_path: str, sname: str):
    global __client_service

    try:
        config = read_config(config_path)
        __client_service = Service()
        sid = __client_service.handle_create_config(config)
        service_name_handler.record_sname_id_pair(sname, sid)
        print(f">>> Create service {sid} successfully.")
        print(f">>> sid: {sid}")
        print(f">>> sname: {sname}")

    except Exception as e:
        print(f">>> Create service error: {e}")


def __upload_config_echo_handler(fut: asyncio.Future):
    content = pickle.loads(fut.result())
    if not content.get("ok", False):
        reason = content.get("reason", "")
        print(f">>> Upload config error, reason: {reason}.")
        return
    print(f">>> Upload config successfully.")


def __upload_encrypted_database_echo_handler(fut: asyncio.Future):
    content = pickle.loads(fut.result())
    if not content.get("ok", False):
        reason = content.get("reason", "")
        print(f">>> Upload encrypted database error, reason: {reason}.")
        return
    print(f">>> Upload encrypted database successfully.")


def __search_echo_handler(fut: asyncio.Future, output_format="raw"):
    global __client_service

    if isinstance(__client_service, Service):
        content = fut.result()
        result = __client_service.sse_module_loader.SSEResult.deserialize(
            content, __client_service.config_object)
        result_list = result.get_result_list()
        output_result_list = [BytesConverter.convert_bytes(identifier_bytes, output_format)
                              for identifier_bytes in result_list]

        print(f">>> The result is {output_result_list}.")


def __multi_search_echo_handler(fut: asyncio.Future, output_format="raw"):
    global __client_service

    if isinstance(__client_service, Service):
        content = pickle.loads(fut.result())
        if not content.get("ok", False):
            reason = content.get("reason", "")
            print(f">>> Multi-search error, reason: {reason}.")
            return
        results = content.get("results", [])
        for i, r in enumerate(results):
            result_obj = __client_service.sse_module_loader.SSEResult.deserialize(
                r["result"], __client_service.config_object)
            result_list = result_obj.get_result_list()
            output_result_list = [BytesConverter.convert_bytes(identifier_bytes, output_format)
                                  for identifier_bytes in result_list]
            print(f">>> Keyword {i + 1} result: {output_result_list}")


def __delete_echo_handler(fut: asyncio.Future):
    content = pickle.loads(fut.result())
    if not content.get("ok", False):
        reason = content.get("reason", "")
        print(f">>> Delete error, reason: {reason}.")
        return
    deleted_count = content.get("deleted_count", 0)
    print(f">>> Delete successfully, deleted {deleted_count} items.")


def __update_echo_handler(fut: asyncio.Future):
    content = pickle.loads(fut.result())
    if not content.get("ok", False):
        reason = content.get("reason", "")
        print(f">>> Update error, reason: {reason}.")
        return
    updated_count = content.get("updated_count", 0)
    print(f">>> Update successfully, updated {updated_count} items.")


async def upload_config(*, sid: str = '', sname: str = ''):
    global __client_service

    try:
        if not sid:
            # get sid from sname
            sid = service_name_handler.get_service_id_by_sname(sname)

        __client_service = Service(sid)

        try:
            await __client_service.handle_upload_config(
                wait=True, wait_callback_func=__upload_config_echo_handler)
        finally:
            await __client_service.close_service()
    except Exception as e:
        print(f">>> Upload config error: {e}")


def generate_key(*, sid: str = '', sname: str = ''):
    global __client_service

    try:
        if not sid:
            # get sid from sname
            sid = service_name_handler.get_service_id_by_sname(sname)

        __client_service = Service(sid)
        __client_service.handle_create_key()
        print(f">>> Generate key successfully.")
    except Exception as e:
        print(f">>> Generate key error: {e}")


def encrypt_database(db: dict = {},
                        db_path : str= "",
                     sid: str = '',
                     sname: str = ''):
    global __client_service

    try:
        if not sid:
            # get sid from sname
            sid = service_name_handler.get_service_id_by_sname(sname)

        __client_service = Service(sid)
        if not db:
            with open(db_path, "r") as f:
                db = json.load(f)


        db = convert_database_keyword_to_bytes(db)
        __client_service.handle_encrypt_database(db)
        print(f">>> Encrypted Database successfully.")
    except Exception as e:
        print(f">>> Create service error: {e}")


def encrypt_database_multi_key(multi_key_db: list = None,
                               db_path: str = "",
                               sid: str = '',
                               sname: str = ''):
    """
    多key索引加密：同一组数据可绑定多个keyword，搜索任意一个keyword都能找到该数据。

    多key数据库格式（JSON list）:
        [
            {"keys": ["keyword1", "keyword2"], "values": ["hex_id1", "hex_id2"]},
            ...
        ]
    """
    global __client_service

    try:
        if not sid:
            sid = service_name_handler.get_service_id_by_sname(sname)

        __client_service = Service(sid)
        if not multi_key_db:
            with open(db_path, "r") as f:
                multi_key_db = json.load(f)

        __client_service.handle_encrypt_database_multi_key(multi_key_db)
        print(f">>> Encrypted multi-key database successfully.")
    except Exception as e:
        print(f">>> Encrypt multi-key database error: {e}")


async def upload_encrypted_database(*, sid: str = '', sname: str = ''):
    global __client_service

    try:
        if not sid:
            # get sid from sname
            sid = service_name_handler.get_service_id_by_sname(sname)

        __client_service = Service(sid)
        try:
            await __client_service.handle_upload_encrypted_database(
                wait=True,
                wait_callback_func=__upload_encrypted_database_echo_handler)
        finally:
            await __client_service.close_service()
    except Exception as e:
        print(f">>> Upload Encrypted Database error: {e}")


async def search(keyword: str, output_format="raw", *, sid: str = '', sname: str = ''):
    if output_format not in BytesConverter.supported_format:
        print(f">>> Unsupported output format {output_format}.")
        return

    global __client_service

    try:
        if not sid:
            # get sid from sname
            sid = service_name_handler.get_service_id_by_sname(sname)
        __client_service = Service(sid)

        try:
            keyword_bytes = bytes(keyword, encoding="utf-8")
            await __client_service.handle_keyword_search(
                keyword_bytes, wait=True, wait_callback_func=functools.partial(__search_echo_handler,
                                                                               output_format=output_format))
        finally:
            await __client_service.close_service()
    except Exception as e:
        print(f">>> Search error: {e}")


async def multi_search(keywords: list, output_format="raw", *, sid: str = '', sname: str = ''):
    """多key检索命令"""
    if output_format not in BytesConverter.supported_format:
        print(f">>> Unsupported output format {output_format}.")
        return

    global __client_service

    try:
        if not sid:
            sid = service_name_handler.get_service_id_by_sname(sname)
        __client_service = Service(sid)

        try:
            keyword_bytes_list = [bytes(kw, encoding="utf-8") for kw in keywords]
            await __client_service.handle_multi_keyword_search(
                keyword_bytes_list, wait=True,
                wait_callback_func=functools.partial(__multi_search_echo_handler,
                                                     output_format=output_format))
        finally:
            await __client_service.close_service()
    except Exception as e:
        print(f">>> Multi-search error: {e}")


async def delete_data(keyword: str = '', indices: list = None, *, sid: str = '', sname: str = ''):
    """删除数据命令"""
    global __client_service

    try:
        if not sid:
            sid = service_name_handler.get_service_id_by_sname(sname)
        __client_service = Service(sid)

        try:
            keyword_bytes = bytes(keyword, encoding="utf-8") if keyword else None
            await __client_service.handle_delete(
                keyword=keyword_bytes, indices=indices,
                wait=True, wait_callback_func=__delete_echo_handler)
        finally:
            await __client_service.close_service()
    except Exception as e:
        print(f">>> Delete error: {e}")


async def update_data(keyword: str = '', entries: list = None,
                      encrypted_data=None, *, sid: str = '', sname: str = ''):
    """更新数据命令"""
    global __client_service

    try:
        if not sid:
            sid = service_name_handler.get_service_id_by_sname(sname)
        __client_service = Service(sid)

        try:
            keyword_bytes = bytes(keyword, encoding="utf-8") if keyword else None
            await __client_service.handle_update(
                keyword=keyword_bytes, encrypted_data=encrypted_data,
                entries=entries,
                wait=True, wait_callback_func=__update_echo_handler)
        finally:
            await __client_service.close_service()
    except Exception as e:
        print(f">>> Update error: {e}")
