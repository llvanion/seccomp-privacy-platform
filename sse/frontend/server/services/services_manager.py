# -*- coding:utf-8 _*-
""" 
LIB-SSE CODE
@author: Jeza Chen
@license: GPL-3.0 License
@file: services_manager.py 
@time: 2022/03/15
@contact: jeza@vip.qq.com
@site:  
@software: PyCharm 
@description: 
"""
import asyncio

from websockets.legacy.server import WebSocketServerProtocol

from frontend.common.constants import MsgType
from frontend.common.utils import shorten_sid
from frontend.server.services.comm import send_message
from frontend.server.services.service import Service
from toolkit.logger.logger import getSSELogger

logger = getSSELogger("sse_server")


class ServicesManager:
    def __init__(self):
        # Lazy-create lock in current running loop to avoid
        # "Future attached to a different loop" in multi-loop environments.
        self._access_dict_lock = None
        self._lock_loop = None
        self._service_dict = {}

    def _get_lock(self):
        running_loop = asyncio.get_running_loop()
        if self._access_dict_lock is None or self._lock_loop is not running_loop:
            self._access_dict_lock = asyncio.Lock()
            self._lock_loop = running_loop
        return self._access_dict_lock

    async def create_service(self, sid: str, websocket: WebSocketServerProtocol):
        short_sid = shorten_sid(sid)  # shorten sid for display and log
        logger.info(f"A new request for service {short_sid} found, creating...")
        # initialize a service first to send control message when the previous connection is not closed
        # a new service created with the same sid just to send init or control messages will not affect the database.
        service = Service(sid, websocket)

        lock = self._get_lock()

        prev_server = None
        async with lock:
            prev_server = self._service_dict.get(sid)

        if prev_server is not None:
            reason = f"Service {short_sid} is already running, we need to wait for the previous connection to close..."
            logger.warning(reason)
            service.send_message(MsgType.CONTROL, reason.encode('utf8'))
            await prev_server.wait_closed()  # wait for the previous socket to close

        async with lock:
            self._service_dict[sid] = service
        clean_task = asyncio.create_task(self.clean_service_when_close_connection(sid, websocket))
        await service.start()  # run forever! do not use asyncio.create_task
        await clean_task

    async def clean_service_when_close_connection(self, sid: str, websocket: WebSocketServerProtocol):
        await websocket.wait_closed()
        await asyncio.sleep(1)
        lock = self._get_lock()
        async with lock:
            service = self._service_dict.get(sid)
            if service is not None and service.websocket is websocket:
                service.close_service()
                del self._service_dict[sid]
        logger.info(f"Clean service {shorten_sid(sid)} successfully.")
