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
"""
import abc
import asyncio
import pickle
import time

from frontend.common.constants import MsgType
from frontend.common.utils import shorten_sid
from frontend.server.services.comm import send_message
from toolkit.logger.logger import getSSELogger
from websockets.legacy.server import WebSocketServerProtocol

import frontend.server.services.file_manager as FileManager
import schemes
from toolkit.bytes_utils import int_to_bytes

logger = getSSELogger("sse_server")
debug_logger = getSSELogger("sse_server_debug")


class SERVICE_STATE:
    NOT_EXISTS = 0
    CONFIG_UPLOADED_BUT_EDB_NOT_UPLOADED = 1
    ALL_READY = 2


class ServiceState(metaclass=abc.ABCMeta):
    """state model, not used currently"""

    def __init__(self):
        self._context = None

    @property
    def context(self):
        return self._context

    @context.setter
    def context(self, context) -> None:
        self._context = context

    @abc.abstractmethod
    def handle_upload_config(self, context, config: dict):
        pass

    @abc.abstractmethod
    def handle_upload_encrypted_database(self, context, edb_bytes: bytes):
        pass

    @abc.abstractmethod
    def handle_search_request(self, context, token_bytes: bytes):
        pass

    @abc.abstractmethod
    def handle_delete_service(self, context):
        pass


class Service:
    def __init__(self, sid, websocket: WebSocketServerProtocol):
        self.sid = sid
        self.websocket = websocket

        self.config = None  # dict type
        self.config_object = None  # SSEConfig type

        self.sse_scheme = None
        self.sse_module_loader = None
        self.edb = None

        if FileManager.check_sid_folder_exist(sid):
            self.config = FileManager.read_service_config(sid)
            self.service_meta = FileManager.read_service_meta(sid)
            self._load_sse_module()
            self._load_config_object()
        else:  # NEW Service
            self.service_meta = {"state": SERVICE_STATE.NOT_EXISTS}


        self.recv_msg_handler = {
            MsgType.CONFIG: self.handle_upload_config,
            MsgType.UPLOAD_DB: self.handle_upload_encrypted_database,
            MsgType.TOKEN: self.handle_search_token,
            MsgType.MULTI_TOKEN: self.handle_multi_search_token,
            MsgType.DELETE: self.handle_delete_data,
            MsgType.UPDATE: self.handle_update_data,
        }

        if self.get_current_service_state() == SERVICE_STATE.ALL_READY:
            # load SSE
            self._load_sse_module()

        self.send_init_echo()  # Finally, send the echo for initialization message
        logger.info(f"Serve Service {self.short_sid}")

    @property
    def short_sid(self) -> str:
        return shorten_sid(self.sid)

    async def start(self):
        await self._recv_message()

    def _store_service_meta(self):
        FileManager.write_service_meta(self.sid, self.service_meta)

    def send_message(self, msg_type: str, content: bytes, **additional_field):
        send_message(self.websocket, self.sid, msg_type, content, **additional_field)

    async def _recv_message(self):
        async for message_bytes in self.websocket:
            message_dict = pickle.loads(message_bytes)
            msg_type = message_dict.get("type")
            sid = message_dict.get("sid")
            if msg_type is None or sid is None or sid != self.sid:
                continue
            content_byte = message_dict.get("content")
            self.recv_msg_handler[msg_type](content_byte, message_dict)

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
        logger.info(f"Load SSE module for service {self.short_sid} successfully.")

    def _load_config_object(self):
        if self.config_object is not None:
            return

        self._load_sse_module()
        self.config_object = self.sse_module_loader.SSEConfig(self.config)  # load scheme config ...
        logger.info(f"Load SSE config for service {self.short_sid} successfully.")

    def _load_sse_scheme(self):
        """load SSE scheme
        @note The SSE module needs to be loaded in advance
        """
        if self.sse_scheme is not None:
            return

        self._load_sse_module()
        self.sse_scheme = self.sse_module_loader.SSEScheme(self.config)  # load scheme construction ...
        logger.info(f"Load SSE scheme for service {self.short_sid} successfully.")

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
        logger.info(f"Load SSE encrypted database for service {self.short_sid} successfully.")

    def _save_sse_encrypted_database(self):
        """Save SSE Encrypted Database back to file"""
        if self.edb is None:
            return
        FileManager.write_encrypted_database(self.sid, self.edb.serialize())
        logger.info(f"Save SSE encrypted database for service {self.short_sid} successfully.")

    def _iter_token_addresses(self, token_object):
        """Best-effort resolve token-related addresses from edb.D (PiBas-like structures)."""
        if token_object is None:
            return []
        if not hasattr(self.edb, "D") or not isinstance(self.edb.D, dict):
            return []
        if not hasattr(token_object, "K1"):
            return []
        if not hasattr(self.config_object, "prf_f"):
            return []

        addresses = []
        counter = 0
        while True:
            addr = self.config_object.prf_f(token_object.K1, int_to_bytes(counter))
            if addr not in self.edb.D:
                break
            addresses.append(addr)
            counter += 1
        return addresses

    def get_current_service_state(self):
        return self.service_meta["state"]

    def send_init_echo(self):
        self.send_message(MsgType.INIT, pickle.dumps({"ok": True, "state": self.get_current_service_state()}))
        logger.info(f"Send initialization echo of service {self.short_sid}.")

    def handle_upload_config(self, config_bytes: bytes, raw_msg_dict: dict):
        logger.info(f"Receive config file from service {self.short_sid}.")

        if self.get_current_service_state() != SERVICE_STATE.NOT_EXISTS:
            logger.info(f"Config of service {self.short_sid} already exists, overwriting...")

        config = pickle.loads(config_bytes)
        # INIT SERVICE
        FileManager.create_sid_folder(self.sid)
        FileManager.write_service_config(self.sid, config)
        self.config = config
        self.service_meta["state"] = SERVICE_STATE.CONFIG_UPLOADED_BUT_EDB_NOT_UPLOADED
        FileManager.write_service_meta(self.sid, self.service_meta)
        self.send_message(MsgType.CONFIG, pickle.dumps({"ok": True}))
        logger.info(f"Store config for service {self.short_sid} successfully.")

    def handle_upload_encrypted_database(self, edb_bytes: bytes, raw_msg_dict: dict):
        logger.info(f"Receive encrypted database from service {self.short_sid}.")

        if self.get_current_service_state() == SERVICE_STATE.NOT_EXISTS:
            reason = f"The config of service {self.short_sid} has not been uploaded."
            self.send_message(MsgType.UPLOAD_DB, pickle.dumps({"ok": False, "reason": reason}))
            logger.error(reason)
            raise ValueError(reason)

        if self.get_current_service_state() == SERVICE_STATE.ALL_READY:
            logger.info(f"Encrypted database of service {self.short_sid} already exists, overwriting...")

        FileManager.write_encrypted_database(self.sid, edb_bytes)
        self.service_meta["state"] = SERVICE_STATE.ALL_READY
        FileManager.write_service_meta(self.sid, self.service_meta)
        self.send_message(MsgType.UPLOAD_DB, pickle.dumps({"ok": True}))
        logger.info(f"Store encrypted database for service {self.short_sid} successfully.")


    def handle_search_token(self, token_bytes: bytes, raw_msg_dict: dict):
        logger.info(f"Receive search token from service {self.short_sid}.")

        if self.get_current_service_state() == SERVICE_STATE.NOT_EXISTS:
            reason = f"The config of service {self.short_sid} has not been uploaded."
            self.send_message(MsgType.RESULT, pickle.dumps({"ok": False, "reason": reason}))
            logger.error(reason)
            raise ValueError(reason)

        if self.get_current_service_state() == SERVICE_STATE.CONFIG_UPLOADED_BUT_EDB_NOT_UPLOADED:
            reason = f"The encrypted database of service {self.short_sid} has not been uploaded."
            self.send_message(MsgType.RESULT, pickle.dumps({"ok": False, "reason": reason}))
            logger.error(reason)
            raise ValueError(reason)

        # Lazy load SSE Scheme and database
        self._load_sse_scheme()
        self._load_sse_encrypted_database()

        tk_digest = raw_msg_dict.get("token_digest")
        tk_object = self.sse_module_loader.SSEToken.deserialize(token_bytes, self.config_object)

        start_time = time.perf_counter()
        result = self.sse_scheme.Search(self.edb, tk_object)
        end_time = time.perf_counter()
        elapsed_ms = (end_time - start_time) * 1000
        debug_logger.debug(f"[{self.short_sid}] Search decryption time: {elapsed_ms:.3f} ms")

        self.send_message(MsgType.RESULT, content=result.serialize(), token_digest=tk_digest)
        logger.info(f"Search for service {self.short_sid} successfully.")

    def handle_multi_search_token(self, content_bytes: bytes, raw_msg_dict: dict):
        logger.info(f"Receive multi-search tokens from service {self.short_sid}.")

        if self.get_current_service_state() == SERVICE_STATE.NOT_EXISTS:
            reason = f"The config of service {self.short_sid} has not been uploaded."
            self.send_message(MsgType.MULTI_RESULT, pickle.dumps({"ok": False, "reason": reason}))
            logger.error(reason)
            raise ValueError(reason)

        if self.get_current_service_state() == SERVICE_STATE.CONFIG_UPLOADED_BUT_EDB_NOT_UPLOADED:
            reason = f"The encrypted database of service {self.short_sid} has not been uploaded."
            self.send_message(MsgType.MULTI_RESULT, pickle.dumps({"ok": False, "reason": reason}))
            logger.error(reason)
            raise ValueError(reason)

        self._load_sse_scheme()
        self._load_sse_encrypted_database()

        content = pickle.loads(content_bytes)
        tokens_data = content.get("tokens", [])
        request_id = raw_msg_dict.get("request_id")
        results = []
        total_start_time = time.perf_counter()
        for token_info in tokens_data:
            token_bytes = token_info.get("token_bytes")
            token_digest = token_info.get("token_digest")
            tk_object = self.sse_module_loader.SSEToken.deserialize(token_bytes, self.config_object)
            start_time = time.perf_counter()
            result = self.sse_scheme.Search(self.edb, tk_object)
            end_time = time.perf_counter()
            elapsed_ms = (end_time - start_time) * 1000
            debug_logger.debug(f"[{self.short_sid}] Multi-search single token decryption time: {elapsed_ms:.3f} ms, token_digest: {token_digest[:16] if token_digest else 'N/A'}...")
            results.append({"token_digest": token_digest, "result": result.serialize()})
        total_end_time = time.perf_counter()
        total_elapsed_ms = (total_end_time - total_start_time) * 1000
        debug_logger.debug(f"[{self.short_sid}] Multi-search total decryption time for {len(tokens_data)} tokens: {total_elapsed_ms:.3f} ms")
        response_content = pickle.dumps({"ok": True, "results": results})
        self.send_message(MsgType.MULTI_RESULT, content=response_content, request_id=request_id)
        logger.info(f"Multi-search for service {self.short_sid} successfully. Processed {len(tokens_data)} tokens.")

    def handle_delete_data(self, content_bytes: bytes, raw_msg_dict: dict):
        logger.info(f"Receive delete request from service {self.short_sid}.")
        if self.get_current_service_state() != SERVICE_STATE.ALL_READY:
            reason = f"The service {self.short_sid} is not ready for delete operation."
            self.send_message(MsgType.DELETE_RESULT, pickle.dumps({"ok": False, "reason": reason}))
            logger.error(reason)
            raise ValueError(reason)
        self._load_sse_scheme()
        self._load_sse_encrypted_database()
        content = pickle.loads(content_bytes)
        delete_token_bytes = content.get("token_bytes")
        delete_indices = content.get("indices", [])
        request_id = raw_msg_dict.get("request_id")
        try:
            start_time = time.perf_counter()
            deleted_count = 0
            if delete_token_bytes:
                tk_object = self.sse_module_loader.SSEToken.deserialize(delete_token_bytes, self.config_object)
                if hasattr(self.sse_scheme, 'Delete'):
                    deleted_count = self.sse_scheme.Delete(self.edb, tk_object, delete_indices)
                else:
                    addresses = self._iter_token_addresses(tk_object)
                    if delete_indices:
                        selected_indices = set(delete_indices)
                        addresses = [addr for idx, addr in enumerate(addresses) if idx in selected_indices]
                    for addr in addresses:
                        if addr in self.edb.D:
                            del self.edb.D[addr]
                            deleted_count += 1
            else:
                if hasattr(self.edb, 'delete'):
                    deleted_count = self.edb.delete(delete_indices)
                elif hasattr(self.edb, 'D') and isinstance(self.edb.D, dict):
                    if delete_indices:
                        keys = list(self.edb.D.keys())
                        for idx in sorted(set(delete_indices), reverse=True):
                            if 0 <= idx < len(keys):
                                del self.edb.D[keys[idx]]
                                deleted_count += 1
                else:
                    reason = f"The encrypted database does not support direct delete operation."
                    self.send_message(MsgType.DELETE_RESULT, pickle.dumps({"ok": False, "reason": reason}))
                    logger.warning(reason)
                    return
            end_time = time.perf_counter()
            elapsed_ms = (end_time - start_time) * 1000
            debug_logger.debug(f"[{self.short_sid}] Delete operation time: {elapsed_ms:.3f} ms, deleted {deleted_count} items")
            self._save_sse_encrypted_database()
            response_content = pickle.dumps({"ok": True, "deleted_count": deleted_count})
            self.send_message(MsgType.DELETE_RESULT, content=response_content, request_id=request_id)
            logger.info(f"Delete for service {self.short_sid} successfully. Deleted {deleted_count} items.")
        except Exception as e:
            reason = f"Delete operation failed: {str(e)}"
            self.send_message(MsgType.DELETE_RESULT, pickle.dumps({"ok": False, "reason": reason}))
            logger.error(reason)

    def handle_update_data(self, content_bytes: bytes, raw_msg_dict: dict):
        logger.info(f"Receive update request from service {self.short_sid}.")
        if self.get_current_service_state() != SERVICE_STATE.ALL_READY:
            reason = f"The service {self.short_sid} is not ready for update operation."
            self.send_message(MsgType.UPDATE_RESULT, pickle.dumps({"ok": False, "reason": reason}))
            logger.error(reason)
            raise ValueError(reason)
        self._load_sse_scheme()
        self._load_sse_encrypted_database()
        content = pickle.loads(content_bytes)
        update_token_bytes = content.get("token_bytes")
        update_data = content.get("encrypted_data")
        update_entries = content.get("entries", [])
        request_id = raw_msg_dict.get("request_id")
        try:
            start_time = time.perf_counter()
            updated_count = 0
            if hasattr(self.sse_scheme, 'Update'):
                if update_token_bytes:
                    tk_object = self.sse_module_loader.SSEToken.deserialize(update_token_bytes, self.config_object)
                    updated_count = self.sse_scheme.Update(self.edb, tk_object, update_data)
                else:
                    updated_count = self.sse_scheme.Update(self.edb, None, update_data)
            elif update_token_bytes and hasattr(self.edb, 'D') and isinstance(self.edb.D, dict):
                tk_object = self.sse_module_loader.SSEToken.deserialize(update_token_bytes, self.config_object)
                addresses = self._iter_token_addresses(tk_object)

                if isinstance(update_data, (list, tuple)):
                    values = list(update_data)
                else:
                    values = [update_data]

                if not values:
                    values = [b""]

                for idx, addr in enumerate(addresses):
                    value = values[idx] if idx < len(values) else values[-1]
                    if value is None:
                        continue
                    self.edb.D[addr] = value
                    updated_count += 1
            elif update_entries and hasattr(self.edb, 'update'):
                for entry in update_entries:
                    addr = entry.get("addr")
                    value = entry.get("value")
                    if addr and value:
                        self.edb.update(addr, value)
                        updated_count += 1
            elif update_entries and hasattr(self.edb, 'D'):
                for entry in update_entries:
                    addr = entry.get("addr")
                    value = entry.get("value")
                    if addr and value:
                        self.edb.D[addr] = value
                        updated_count += 1
            else:
                reason = f"The SSE scheme or encrypted database does not support update operation."
                self.send_message(MsgType.UPDATE_RESULT, pickle.dumps({"ok": False, "reason": reason}))
                logger.warning(reason)
                return
            end_time = time.perf_counter()
            elapsed_ms = (end_time - start_time) * 1000
            debug_logger.debug(f"[{self.short_sid}] Update operation time: {elapsed_ms:.3f} ms, updated {updated_count} items")
            self._save_sse_encrypted_database()
            response_content = pickle.dumps({"ok": True, "updated_count": updated_count})
            self.send_message(MsgType.UPDATE_RESULT, content=response_content, request_id=request_id)
            logger.info(f"Update for service {self.short_sid} successfully. Updated {updated_count} items.")
        except Exception as e:
            reason = f"Update operation failed: {str(e)}"
            self.send_message(MsgType.UPDATE_RESULT, pickle.dumps({"ok": False, "reason": reason}))
            logger.error(reason)

    def close_service(self):
        self._store_service_meta()

    async def wait_closed(self):
        await self.websocket.wait_closed()
