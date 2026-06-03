# -*- coding:utf-8 _*-
""" 
LIB-SSE CODE
@author: Jeza Chen
@license: GPL-3.0 License
@file: service.py 
@time: 2022/03/15
@contact: jeza@vip.qq.com
@site:  
@software: PyCharm 
@description:

@note: proxy model, state model
@note2: Require server response to modify upload status
"""
import asyncio
import functools
import hashlib
import itertools
import os
import time
import uuid

import websockets
import websockets.client
from websockets.exceptions import InvalidURI, InvalidHandshake

import frontend.client.services.file_manager as FileManager
import schemes
from frontend.common.constants import MsgType
from frontend.common.utils import shorten_sid
from frontend.common.wire import decode_content, dumps_message, encode_content, loads_message
# bits represents status
from frontend.constants import KEY_TYPE, KEY_SID, TYPE_INIT
from global_config import ClientConfig
from toolkit.logger.logger import getSSELogger

logger = getSSELogger("sse_client",
                      console_log_level=ClientConfig.CONSOLE_LOG_LEVEL,
                      file_log_level=ClientConfig.FILE_LOG_LEVEL)

_BIT_CONFIG_CREATED = 0b00001
_BIT_CONFIG_UPLOADED = 0b00010
_BIT_KEY_CREATED = 0b00100
_BIT_DB_ENCRYPTED = 0b01000
_BIT_DB_UPLOADED = 0b10000

_EMPTY_STATE = 0b00000


class SERVICE_STATE:
    NOT_EXISTS = 0
    CONFIG_UPLOADED_BUT_EDB_NOT_UPLOADED = 1
    ALL_READY = 2


class ClientServiceState:

    @staticmethod
    def is_config_created(state_bit_set):
        return bool(state_bit_set & _BIT_CONFIG_CREATED)

    @staticmethod
    def is_config_uploaded(state_bit_set):
        return bool(state_bit_set & _BIT_CONFIG_UPLOADED)

    @staticmethod
    def is_key_created(state_bit_set):
        return bool(state_bit_set & _BIT_KEY_CREATED)

    @staticmethod
    def is_db_encrypted(state_bit_set):
        return bool(state_bit_set & _BIT_DB_ENCRYPTED)

    @staticmethod
    def is_db_uploaded(state_bit_set):
        return bool(state_bit_set & _BIT_DB_UPLOADED)

    @staticmethod
    def set_config_created(state_bit_set, is_config_created: bool):
        if is_config_created:
            return state_bit_set | _BIT_CONFIG_CREATED
        else:
            return state_bit_set & ~_BIT_CONFIG_CREATED

    @staticmethod
    def set_config_uploaded(state_bit_set, is_config_uploaded: bool):
        if is_config_uploaded:
            return state_bit_set | _BIT_CONFIG_UPLOADED
        else:
            return state_bit_set & ~_BIT_CONFIG_UPLOADED

    @staticmethod
    def set_key_created(state_bit_set, is_key_created: bool):
        if is_key_created:
            return state_bit_set | _BIT_KEY_CREATED
        else:
            return state_bit_set & ~_BIT_KEY_CREATED

    @staticmethod
    def set_db_encrypted(state_bit_set, is_db_encrypted: bool):
        if is_db_encrypted:
            return state_bit_set | _BIT_DB_ENCRYPTED
        else:
            return state_bit_set & ~_BIT_DB_ENCRYPTED

    @staticmethod
    def set_db_uploaded(state_bit_set, is_db_uploaded: bool):
        if is_db_uploaded:
            return state_bit_set | _BIT_DB_UPLOADED
        else:
            return state_bit_set & ~_BIT_DB_UPLOADED


def _check_config_valid(config: dict):
    def _try_load_sse_scheme(_scheme_name: str):
        return schemes.load_sse_module(_scheme_name)

    scheme_name = config.get("scheme")
    if scheme_name is None:
        raise ValueError("The scheme parameter is required in the configuration")

    try:
        module_loader = _try_load_sse_scheme(scheme_name)
        module_loader.SSEConfig(config)
        return True
    except Exception:
        return False


def _add_salt_to_config(config: dict):
    if "salt" in config:
        return ValueError("The config already has salt value.")

    config["salt"] = os.urandom(32).hex()


def _calculate_sid_by_config_content(config: dict) -> str:
    import hashlib
    config_bytes = encode_content(config)
    config_digest = hashlib.sha256(config_bytes).digest()
    sid = config_digest.hex()
    return sid


class Service:
    def __init__(self, sid=""):
        logger.info("Create a service")

        self.sid = sid
        self.websocket = None

        self.config = None  # dict type
        self.config_object = None  # SSEConfig type

        if FileManager.check_sid_local_file_valid(sid):
            self.config = FileManager.read_service_config(sid)
            self.service_meta = FileManager.read_service_meta(sid)
        else:
            self.service_meta = {"state": _EMPTY_STATE}

        self.sse_scheme = None
        self.sse_module_loader = None
        self.edb = None
        self.key = None

        if ClientServiceState.is_config_created(self.get_current_service_state()):
            # load SSE module if config exists
            self._load_sse_module()
            self._load_config_object()

        self.recv_msg_handler = {
            MsgType.CONFIG: self.handle_upload_config_echo,
            MsgType.UPLOAD_DB: self.handle_upload_encrypted_database_echo,
            MsgType.RESULT: self.handle_result,
            MsgType.CONTROL: self.handle_control_message,
            MsgType.MULTI_RESULT: self.handle_multi_result,
            MsgType.DELETE_RESULT: self.handle_delete_result,
            MsgType.UPDATE_RESULT: self.handle_update_result,
        }

        self.echo_handler = {
            MsgType.CONFIG: [],
            MsgType.UPLOAD_DB: []
        }

        self.echo_futures = {}
        self.result_futures = {}
        self.request_futures = {}  # for multi-search / delete / update
        logger.info(f"Create a service {self.short_sid} successfully.")

    @property
    def short_sid(self) -> str:
        return shorten_sid(self.sid)

    def register_echo_handler_once(self, msg_type: str, handler):
        if msg_type not in self.echo_handler:
            self.echo_handler[msg_type] = []

        self.echo_handler[msg_type].append(handler)
        logger.info(f"[{self.short_sid}] Register an echo handler for {msg_type}.")

    def register_upload_echo_future_once(self, msg_type: str, fut: asyncio.Future):
        if msg_type not in self.echo_futures:
            self.echo_futures[msg_type] = []

        self.echo_futures[msg_type].append(fut)
        logger.info(f"[{self.short_sid}] Register an echo future handler for {msg_type}.")

    def register_result_future_once(self, tk_digest: str, fut: asyncio.Future):
        if tk_digest not in self.result_futures:
            self.result_futures[tk_digest] = []
        self.result_futures[tk_digest].append(fut)
        logger.info(f"[{self.short_sid}] Register an result future handler for token {tk_digest}.")

    def register_request_future_once(self, request_id: str, fut: asyncio.Future):
        if request_id not in self.request_futures:
            self.request_futures[request_id] = []
        self.request_futures[request_id].append(fut)
        logger.info(f"[{self.short_sid}] Register a request future handler for {request_id}.")

    async def load_websocket(self):
        if self.websocket is not None:
            return

        uri = ClientConfig.SERVER_URI
        logger.info(f"[{self.short_sid}] Connecting to server {uri}.")
        # config =
        try:
            websocket = await websockets.client.connect(uri, max_size=None)
            event = {
                KEY_TYPE: TYPE_INIT,
                KEY_SID: self.sid
            }

            await websocket.send(dumps_message(event))

            init_echo = await websocket.recv()
            echo_dict = loads_message(init_echo)
            if "content" not in echo_dict:
                logger.error(f"[{self.short_sid}] Init echo error.")
                raise ValueError("Init echo error.")
            echo_content = decode_content(echo_dict.get("content"))
            if echo_content.get("ok"):
                logger.info(f"[{self.short_sid}] Connect to server {uri} successfully.")
                self.websocket = websocket
                asyncio.create_task(self._recv_message())

                server_state = echo_content.get("state", 0)
                logger.info(f"[{self.short_sid}] The service status on the server side is {server_state}")
                self.update_current_client_service_state_by_server_service_state(server_state)
            else:
                logger.error(f"[{self.short_sid}] Init echo error.")
                raise ValueError("Init echo error.")
        except (InvalidURI, InvalidHandshake, TimeoutError, websockets.ConnectionClosed) as e:
            reason = f"[{self.short_sid}] Init echo error: {e}"
            logger.error(reason)
            raise ValueError(reason)

    def _store_service_meta(self):
        FileManager.write_service_meta(self.sid, self.service_meta)
        logger.info(f"[{self.short_sid}] Store meta successfully.")

    async def _send_message(self, msg_type: str, content: bytes, **additional_field):
        await self.load_websocket()  # check if websocket is initialized
        msg_dict = {
            "type": msg_type,
            "sid": self.sid,
            "content": content
        }
        msg_dict.update(additional_field)
        await self.websocket.send(dumps_message(msg_dict))

    async def _recv_message(self):
        async for message_bytes in self.websocket:
            message_dict = loads_message(message_bytes)
            msg_type = message_dict.get("type")
            sid = message_dict.get("sid")
            if msg_type is None or sid is None or sid != self.sid:
                continue
            content_byte = message_dict.get("content")
            handler = self.recv_msg_handler.get(msg_type)
            if handler is not None:
                handler(content_byte)

            # echo handler
            if self.echo_handler.get(msg_type):
                for handler in self.echo_handler.get(msg_type, []):
                    handler(content_byte)
                self.echo_handler[msg_type] = []  # clear

            # echo future handler
            if self.echo_futures.get(msg_type):
                for fut in self.echo_futures.get(msg_type, []):
                    fut.set_result(content_byte)
                self.echo_futures[msg_type] = []  # clear

            # result future handler
            if msg_type == MsgType.RESULT:
                token_digest = message_dict.get("token_digest")
                for fut in self.result_futures.get(token_digest, []):
                    fut.set_result(content_byte)
                self.result_futures[token_digest] = []

            # request future handler (for multi-search / delete / update)
            if msg_type in (MsgType.MULTI_RESULT, MsgType.DELETE_RESULT, MsgType.UPDATE_RESULT):
                request_id = message_dict.get("request_id")
                if request_id and request_id in self.request_futures:
                    for fut in self.request_futures.get(request_id, []):
                        fut.set_result(content_byte)
                    self.request_futures[request_id] = []

    def _load_sse_module(self):
        """load SSE module by service config.
        service config must have scheme attribute
        """
        if self.sse_module_loader is not None:
            return

        if self.config is None:
            raise AttributeError(f"The config of this service {self.short_sid} is None.")
        if "scheme" not in self.config:
            raise AttributeError(f"The config of this service {self.short_sid} does not have 'scheme' attribute.")
        scheme_name = self.config["scheme"]
        self.sse_module_loader = schemes.load_sse_module(scheme_name)
        logger.info(f"[{self.short_sid}] Load SSE Module successfully.")

    def _load_config_object(self):
        if self.config_object is not None:
            return

        self._load_sse_module()
        self.config_object = self.sse_module_loader.SSEConfig(self.config)  # load scheme config ...
        logger.info(f"[{self.short_sid}] Load SSE config object successfully.")

    def _load_sse_scheme(self):
        """load SSE scheme
        @note The SSE module needs to be loaded in advance
        """
        if self.sse_scheme is not None:
            return

        self._load_sse_module()
        self.sse_scheme = self.sse_module_loader.SSEScheme(self.config)  # load scheme construction ...
        logger.info(f"[{self.short_sid}] Load SSE scheme successfully.")

    def _load_sse_encrypted_database(self):
        """load SSE Encrypted Database
        @note The SSE module needs to be loaded in advance
        """
        if self.edb is not None:
            return

        self._load_sse_module()
        self._load_config_object()

        edb_bytes = FileManager.read_encrypted_database(self.sid)
        EDBClass = self.sse_module_loader.SSEEncryptedDatabase
        self.edb = EDBClass.deserialize(edb_bytes, self.config_object)
        logger.info(f"[{self.short_sid}] Load SSE encrypted database successfully.")

    def _load_sse_key(self):
        self._load_sse_module()
        self._load_config_object()

        key_bytes = FileManager.read_key(self.sid)
        KeyClass = self.sse_module_loader.SSEKey
        self.key = KeyClass.deserialize(key_bytes, self.config_object)
        logger.info(f"[{self.short_sid}] Load SSE Key successfully.")

    def get_current_service_state(self):
        if self.service_meta is None:
            return _EMPTY_STATE
        return self.service_meta["state"]

    def set_current_service_state(self, new_state):
        self.service_meta["state"] = new_state

    def update_current_client_service_state_by_server_service_state(self, service_state):
        # todo can be optimized
        if service_state == SERVICE_STATE.NOT_EXISTS:
            self.set_current_service_state(
                ClientServiceState.set_config_uploaded(self.get_current_service_state(), False))
            self.set_current_service_state(
                ClientServiceState.set_db_uploaded(self.get_current_service_state(), False))
        elif service_state == SERVICE_STATE.CONFIG_UPLOADED_BUT_EDB_NOT_UPLOADED:
            self.set_current_service_state(
                ClientServiceState.set_config_uploaded(self.get_current_service_state(), True))
            self.set_current_service_state(
                ClientServiceState.set_db_uploaded(self.get_current_service_state(), False))
        elif service_state == SERVICE_STATE.ALL_READY:
            self.set_current_service_state(
                ClientServiceState.set_config_uploaded(self.get_current_service_state(), True))
            self.set_current_service_state(
                ClientServiceState.set_db_uploaded(self.get_current_service_state(), True))

    def handle_create_config(self, config: dict, overwrite=True):
        if ClientServiceState.is_config_created(self.get_current_service_state()):
            if not overwrite:
                raise ValueError(f"The config of service {self.short_sid} has been already created.")
            logger.info(f"[{self.short_sid}] Config already exists, overwriting...")

        _check_config_valid(config)
        _add_salt_to_config(config)  # add salt

        # INIT SERVICE
        self.sid = _calculate_sid_by_config_content(config)  # generated sid
        FileManager.create_sid_folder(self.sid)
        FileManager.write_service_config(self.sid, config)
        # Reset states for overwrite scenario
        self._service_state = 0
        self.config = config
        self.set_current_service_state(ClientServiceState.set_config_created(self.get_current_service_state(), True))
        self._store_service_meta()
        logger.info(f"[{self.short_sid}] Create service {self.short_sid} successfully!")
        return self.sid

    def _default_upload_config_echo_future_handler(self, fut: asyncio.Future):
        content = decode_content(fut.result())
        if not content.get("ok", False):
            reason = content.get("reason", "")
            logger.error(f"[{self.short_sid}] Upload config error, reason: {reason}")
            return
        logger.info(f"[{self.short_sid}] Upload config successfully")

    def _default_upload_encrypted_database_echo_future_handler(self, fut: asyncio.Future):
        content = decode_content(fut.result())
        if not content.get("ok", False):
            reason = content.get("reason", "")
            logger.error(f"[{self.short_sid}] Upload encrypted database error, reason: {reason}")
            return
        logger.info(f"[{self.short_sid}] Upload encrypted database successfully")

    async def handle_upload_config(self,
                                   wait=False,
                                   wait_callback_func=None,
                                   overwrite=True):
        # todo echo处理函数能不能整合在wait_callback_func里面去呢，而不用两个处理逻辑
        await self.load_websocket()

        if ClientServiceState.is_config_uploaded(self.get_current_service_state()):
            if not overwrite:
                reason = f"The config of service {self.short_sid} has been already uploaded."
                logger.error(reason)
                raise ValueError(reason)
            logger.info(f"[{self.short_sid}] Config already uploaded, overwriting...")
            self.set_current_service_state(ClientServiceState.set_config_uploaded(self.get_current_service_state(), False))
        if not ClientServiceState.is_config_created(self.get_current_service_state()):
            reason = f"The config of service {self.short_sid} is not found."
            logger.error(reason)
            raise ValueError(reason)

        fut = None
        if wait:
            if wait_callback_func is None:
                wait_callback_func = self._default_upload_config_echo_future_handler

            # Get the current event loop.
            loop = asyncio.get_running_loop()
            # Create a new Future object.
            fut = loop.create_future()
            fut.add_done_callback(wait_callback_func)
            self.register_upload_echo_future_once(MsgType.CONFIG, fut)

        await self._send_message(MsgType.CONFIG, encode_content(self.config))
        logger.info(f"[{self.short_sid}] Uploading config.")

        if wait:
            await asyncio.wait_for(fut, 60)

    def handle_upload_config_echo(self, content_bytes: bytes):
        content = decode_content(content_bytes)
        if not content.get("ok", False):
            reason = content.get("reason", "")
            logger.error(f"[{self.short_sid}] Upload config error, reason: {reason}")
            return

        self.set_current_service_state(ClientServiceState.set_config_uploaded(self.get_current_service_state(), True))
        self._store_service_meta()
        logger.info(f"[{self.short_sid}] Upload config successfully")

    def handle_upload_encrypted_database_echo(self, content_bytes: bytes):
        content = decode_content(content_bytes)
        if not content.get("ok", False):
            reason = content.get("reason", "")
            logger.error(f"[{self.short_sid}] Upload encrypted database error, reason: {reason}")
            return

        self.set_current_service_state(ClientServiceState.set_db_uploaded(self.get_current_service_state(), True))
        self._store_service_meta()
        logger.info(f"[{self.short_sid}] Upload encrypted database successfully")
        FileManager.delete_encrypted_database(self.sid)
        logger.info(f"[{self.short_sid}] Delete the local encrypted database successfully")

    def handle_create_key(self, overwrite=True):
        if ClientServiceState.is_key_created(self.get_current_service_state()):
            if not overwrite:
                reason = f"The SSE key of service {self.short_sid} has been already created."
                logger.error(reason)
                raise ValueError(reason)
            logger.info(f"[{self.short_sid}] SSE key already exists, overwriting...")
        if not ClientServiceState.is_config_created(self.get_current_service_state()):
            reason = f"The config of service {self.short_sid} is not found."
            logger.error(reason)
            raise ValueError(reason)

        self._load_config_object()
        self._load_sse_scheme()
        sse_key = self.sse_scheme.KeyGen()
        FileManager.write_key(self.sid, sse_key.serialize())
        self.set_current_service_state(ClientServiceState.set_key_created(self.get_current_service_state(), True))
        self._store_service_meta()

    def handle_encrypt_database(self, database: dict, overwrite=True):
        if ClientServiceState.is_db_encrypted(self.get_current_service_state()):
            if not overwrite:
                reason = f"The database of service {self.short_sid} has been already created."
                logger.error(reason)
                raise ValueError(reason)
            logger.info(f"[{self.short_sid}] Encrypted database already exists, overwriting...")
        if not ClientServiceState.is_config_created(self.get_current_service_state()):
            reason = f"The config of service {self.short_sid} is not found."
            logger.error(reason)
            raise ValueError(reason)
        if not ClientServiceState.is_key_created(self.get_current_service_state()):
            reason = f"The key of service {self.short_sid} is not found."
            logger.error(reason)
            raise ValueError(reason)

        self._load_sse_scheme()
        self._load_sse_key()
        self.edb = self.sse_scheme.EDBSetup(self.key, database)
        FileManager.write_encrypted_database(self.sid, self.edb.serialize())
        self.set_current_service_state(ClientServiceState.set_db_encrypted(self.get_current_service_state(), True))
        self._store_service_meta()

    def handle_encrypt_database_multi_key(self, multi_key_database: list):
        """
        多key索引加密：同一组数据绑定多个keyword，搜索任意一个keyword即可找到该数据。

        :param multi_key_database: 多key格式的数据库，格式为:
            [
                {"keys": ["keyword1", "keyword2"], "values": ["hex_id1", "hex_id2"]},
                ...
            ]
        每条数据的 values 会在其所有 keys 下各建一份索引，加密后上传到服务器。
        搜索任意一个keyword都能返回对应的数据。
        """
        from toolkit.database_utils import convert_multi_key_database
        inverted_index_db = convert_multi_key_database(multi_key_database)
        logger.info(f"[{self.short_sid}] Converted multi-key database: "
                    f"{len(multi_key_database)} entries -> "
                    f"{len(inverted_index_db)} keywords in inverted index.")
        self.handle_encrypt_database(inverted_index_db)

    async def handle_upload_encrypted_database(self,
                                               wait=False,
                                               wait_callback_func=None,
                                               overwrite=True):

        await self.load_websocket()

        if ClientServiceState.is_db_uploaded(self.get_current_service_state()):
            if not overwrite:
                reason = f"The database of service {self.short_sid} has been already uploaded."
                logger.error(reason)
                raise ValueError(reason)
            logger.info(f"[{self.short_sid}] Encrypted database already uploaded, overwriting...")
            self.set_current_service_state(ClientServiceState.set_db_uploaded(self.get_current_service_state(), False))
        if not ClientServiceState.is_config_uploaded(self.get_current_service_state()):
            reason = f"The config of service {self.short_sid} has not been uploaded."
            logger.error(reason)
            raise ValueError(reason)
        if not ClientServiceState.is_key_created(self.get_current_service_state()):
            reason = f"The key of service {self.short_sid} is not found."
            logger.error(reason)
            raise ValueError(reason)

        self._load_sse_encrypted_database()

        fut = None
        if wait:
            if wait_callback_func is None:
                wait_callback_func = self._default_upload_encrypted_database_echo_future_handler
            # Get the current event loop.
            loop = asyncio.get_running_loop()
            # Create a new Future object.
            fut = loop.create_future()
            fut.add_done_callback(wait_callback_func)
            self.register_upload_echo_future_once(MsgType.UPLOAD_DB, fut)

        await self._send_message(MsgType.UPLOAD_DB, self.edb.serialize())
        logger.info(f"[{self.short_sid}] Uploading encrypted database.")

        if wait:
            await asyncio.wait_for(fut, 60)

    async def handle_keyword_search(self, keyword: bytes,
                                    wait=False,
                                    wait_callback_func=None):
        await self.load_websocket()

        if not ClientServiceState.is_db_uploaded(self.get_current_service_state()):
            reason = f"The database of service {self.short_sid} has not been uploaded."
            logger.error(reason)
            raise ValueError(reason)

        self._load_sse_scheme()
        self._load_sse_key()

        fut = None
        if wait:
            if wait_callback_func is None:
                wait_callback_func = self.handle_result_future
            # Get the current event loop.
            loop = asyncio.get_running_loop()
            # Create a new Future object.
            fut = loop.create_future()
            fut.add_done_callback(wait_callback_func)
            self.register_upload_echo_future_once(MsgType.RESULT, fut)

        token = self.sse_scheme.TokenGen(self.key, keyword)
        token_bytes = token.serialize()
        token_digest = hashlib.sha256(token_bytes).digest()

        start_time = time.perf_counter()
        await self._send_message(MsgType.TOKEN,
                                 token_bytes,
                                 token_digest=token_digest)
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(f"[{self.short_sid}] Token generation + send time: {elapsed_ms:.3f} ms")
        logger.info(f"[{self.short_sid}] Uploading search token.")

        if wait:
            await asyncio.wait_for(fut, 60)
            return fut.result()

    def handle_result(self, result_bytes: bytes):
        result = self.sse_module_loader.SSEResult.deserialize(result_bytes, self.config_object)
        logger.info(f"[{self.short_sid}] The result is {result}.")
        return result

    def handle_result_future(self, fut: asyncio.Future):
        content = fut.result()
        result = self.sse_module_loader.SSEResult.deserialize(content, self.config_object)
        logger.info(f"[{self.short_sid}] The result is {result}.")

    # ===================== 多key检索 =====================

    async def handle_multi_keyword_search(self, keywords: list,
                                          wait=False,
                                          wait_callback_func=None):
        """多key检索：一次性发送多个keyword的token到服务器"""
        await self.load_websocket()

        if not ClientServiceState.is_db_uploaded(self.get_current_service_state()):
            reason = f"The database of service {self.short_sid} has not been uploaded."
            logger.error(reason)
            raise ValueError(reason)

        self._load_sse_scheme()
        self._load_sse_key()

        request_id = str(uuid.uuid4())
        fut = None
        if wait:
            if wait_callback_func is None:
                wait_callback_func = self.handle_multi_result_future
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            fut.add_done_callback(wait_callback_func)
            self.register_request_future_once(request_id, fut)

        tokens_data = []
        total_start = time.perf_counter()
        for keyword in keywords:
            start_time = time.perf_counter()
            token = self.sse_scheme.TokenGen(self.key, keyword)
            token_bytes = token.serialize()
            token_digest = hashlib.sha256(token_bytes).digest()
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.debug(f"[{self.short_sid}] TokenGen time for keyword: {elapsed_ms:.3f} ms")
            tokens_data.append({
                "token_bytes": token_bytes,
                "token_digest": token_digest,
            })
        total_elapsed = (time.perf_counter() - total_start) * 1000
        logger.debug(f"[{self.short_sid}] Total TokenGen time for {len(keywords)} keywords: {total_elapsed:.3f} ms")

        content = encode_content({"tokens": tokens_data})
        await self._send_message(MsgType.MULTI_TOKEN, content, request_id=request_id)
        logger.info(f"[{self.short_sid}] Uploading {len(keywords)} search tokens (multi-search).")

        if wait:
            await asyncio.wait_for(fut, 120)

    def handle_multi_result(self, result_bytes: bytes):
        """处理多key检索结果消息"""
        content = decode_content(result_bytes)
        if not content.get("ok", False):
            reason = content.get("reason", "")
            logger.error(f"[{self.short_sid}] Multi-search error, reason: {reason}")
            return content
        results = content.get("results", [])
        parsed_results = []
        for r in results:
            result_obj = self.sse_module_loader.SSEResult.deserialize(r["result"], self.config_object)
            parsed_results.append({
                "token_digest": r["token_digest"],
                "result": result_obj,
            })
        logger.info(f"[{self.short_sid}] Multi-search returned {len(parsed_results)} results.")
        return parsed_results

    def handle_multi_result_future(self, fut: asyncio.Future):
        content = fut.result()
        parsed = decode_content(content)
        if not parsed.get("ok", False):
            reason = parsed.get("reason", "")
            logger.error(f"[{self.short_sid}] Multi-search error, reason: {reason}")
            return
        results = parsed.get("results", [])
        for r in results:
            result_obj = self.sse_module_loader.SSEResult.deserialize(r["result"], self.config_object)
            logger.info(f"[{self.short_sid}] Multi-search result: {result_obj}")

    # ===================== 删除数据 =====================

    async def handle_delete(self, keyword: bytes = None,
                            indices: list = None,
                            wait=False,
                            wait_callback_func=None):
        """删除数据：通过keyword的token或直接按索引删除"""
        await self.load_websocket()

        if not ClientServiceState.is_db_uploaded(self.get_current_service_state()):
            reason = f"The database of service {self.short_sid} has not been uploaded."
            logger.error(reason)
            raise ValueError(reason)

        self._load_sse_scheme()
        self._load_sse_key()

        request_id = str(uuid.uuid4())
        fut = None
        if wait:
            if wait_callback_func is None:
                wait_callback_func = self.handle_delete_result_future
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            fut.add_done_callback(wait_callback_func)
            self.register_request_future_once(request_id, fut)

        delete_content = {"indices": indices or []}
        if keyword is not None:
            start_time = time.perf_counter()
            token = self.sse_scheme.TokenGen(self.key, keyword)
            token_bytes = token.serialize()
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.debug(f"[{self.short_sid}] Delete TokenGen time: {elapsed_ms:.3f} ms")
            delete_content["token_bytes"] = token_bytes

        await self._send_message(MsgType.DELETE, encode_content(delete_content), request_id=request_id)
        logger.info(f"[{self.short_sid}] Sending delete request.")

        if wait:
            await asyncio.wait_for(fut, 60)

    def handle_delete_result(self, result_bytes: bytes):
        """处理删除结果消息"""
        content = decode_content(result_bytes)
        if not content.get("ok", False):
            reason = content.get("reason", "")
            logger.error(f"[{self.short_sid}] Delete error, reason: {reason}")
            return content
        deleted_count = content.get("deleted_count", 0)
        logger.info(f"[{self.short_sid}] Delete successfully, deleted {deleted_count} items.")
        return content

    def handle_delete_result_future(self, fut: asyncio.Future):
        content = decode_content(fut.result())
        if not content.get("ok", False):
            reason = content.get("reason", "")
            logger.error(f"[{self.short_sid}] Delete error, reason: {reason}")
            return
        deleted_count = content.get("deleted_count", 0)
        logger.info(f"[{self.short_sid}] Delete successfully, deleted {deleted_count} items.")

    # ===================== 更新数据 =====================

    async def handle_update(self, keyword: bytes = None,
                            encrypted_data=None,
                            entries: list = None,
                            wait=False,
                            wait_callback_func=None):
        """更新数据：通过keyword的token或直接按条目更新"""
        await self.load_websocket()

        if not ClientServiceState.is_db_uploaded(self.get_current_service_state()):
            reason = f"The database of service {self.short_sid} has not been uploaded."
            logger.error(reason)
            raise ValueError(reason)

        self._load_sse_scheme()
        self._load_sse_key()

        request_id = str(uuid.uuid4())
        fut = None
        if wait:
            if wait_callback_func is None:
                wait_callback_func = self.handle_update_result_future
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            fut.add_done_callback(wait_callback_func)
            self.register_request_future_once(request_id, fut)

        update_content = {
            "encrypted_data": encrypted_data,
            "entries": entries or [],
        }
        if keyword is not None:
            start_time = time.perf_counter()
            token = self.sse_scheme.TokenGen(self.key, keyword)
            token_bytes = token.serialize()
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.debug(f"[{self.short_sid}] Update TokenGen time: {elapsed_ms:.3f} ms")
            update_content["token_bytes"] = token_bytes

        await self._send_message(MsgType.UPDATE, encode_content(update_content), request_id=request_id)
        logger.info(f"[{self.short_sid}] Sending update request.")

        if wait:
            await asyncio.wait_for(fut, 60)

    def handle_update_result(self, result_bytes: bytes):
        """处理更新结果消息"""
        content = decode_content(result_bytes)
        if not content.get("ok", False):
            reason = content.get("reason", "")
            logger.error(f"[{self.short_sid}] Update error, reason: {reason}")
            return content
        updated_count = content.get("updated_count", 0)
        logger.info(f"[{self.short_sid}] Update successfully, updated {updated_count} items.")
        return content

    def handle_update_result_future(self, fut: asyncio.Future):
        content = decode_content(fut.result())
        if not content.get("ok", False):
            reason = content.get("reason", "")
            logger.error(f"[{self.short_sid}] Update error, reason: {reason}")
            return
        updated_count = content.get("updated_count", 0)
        logger.info(f"[{self.short_sid}] Update successfully, updated {updated_count} items.")

    def handle_control_message(self, msg_bytes: bytes):
        msg_str = msg_bytes.decode(encoding='utf8')
        logger.warning(f"[{self.short_sid}] Receive control message: {msg_str}.")

    async def close_service(self):
        self._store_service_meta()
        if self.websocket is not None:
            await self.websocket.close()
        logger.info(f"[{self.short_sid}] close Service successfully.")


async def main():
    # simple test
    from schemes.CJJ14.PiBas.config import DEFAULT_CONFIG as PI_BAS_DEFAULT_CONFIG

    service = Service()

    from test.tools.faker import fake_db_for_inverted_index_based_sse
    from test.test_sse_schemes.test_CJJ14_PiBas import TEST_KEYWORD_SIZE
    from test.test_sse_schemes.test_CJJ14_PiBas import TEST_FILE_ID_SIZE

    db = fake_db_for_inverted_index_based_sse(TEST_KEYWORD_SIZE,
                                              TEST_FILE_ID_SIZE,
                                              1000,
                                              db_w_size_range=(1, 200))
    service.handle_create_config(PI_BAS_DEFAULT_CONFIG)
    service.handle_create_key()
    service.handle_encrypt_database(db)
    await service.handle_upload_config(wait=True)

    while True:
        if ClientServiceState.is_config_uploaded(service.get_current_service_state()):
            break
        await asyncio.sleep(1)

    await service.handle_upload_encrypted_database(wait=True)

    while True:
        if ClientServiceState.is_db_uploaded(service.get_current_service_state()):
            break
        await asyncio.sleep(1)

    def _compare_result(fut: asyncio.Future, actual_result):
        from schemes.CJJ14.PiBas.structures import PiBasResult
        return_result_bytes = fut.result()
        return_result = PiBasResult.deserialize(return_result_bytes)
        assert return_result.result == actual_result

    for keyword in itertools.islice(db.keys(), 10):
        # service.register_echo_handler_once(MsgType.RESULT, functools.partial(_compare_result, actual_result=db[keyword]))
        await service.handle_keyword_search(keyword,
                                            wait=True,
                                            wait_callback_func=functools.partial(_compare_result,
                                                                                 actual_result=db[keyword]))

    await service.close_service()


async def main2():
    # simple test
    from schemes.CJJ14.PiBas.config import DEFAULT_CONFIG as PI_BAS_DEFAULT_CONFIG

    service = Service()

    from test.tools.faker import fake_db_for_inverted_index_based_sse
    from test.test_sse_schemes.test_CJJ14_PiBas import TEST_KEYWORD_SIZE
    from test.test_sse_schemes.test_CJJ14_PiBas import TEST_FILE_ID_SIZE

    db = fake_db_for_inverted_index_based_sse(TEST_KEYWORD_SIZE,
                                              TEST_FILE_ID_SIZE,
                                              1000,
                                              db_w_size_range=(1, 200))
    service.handle_create_config(PI_BAS_DEFAULT_CONFIG)
    service.handle_create_key()
    service.handle_encrypt_database(db)
    await service.handle_upload_config(wait=True)
    await service.close_service()


if __name__ == "__main__":
    asyncio.run(main())
