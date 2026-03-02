# -*- coding:utf-8 _*-
"""
LIB-SSE CODE
@author: Jeza Chen
@license: GPL-3.0 License
@file: services_manager.py
@time: 2023/12/17
@contact: jeza@vip.qq.com
@site:
@software: PyCharm
@description: constants shared by clients and servers
"""


# Types of messages that can be sent between the client and server
class MsgType:
    # init echo
    INIT = "init"
    # service config
    CONFIG = "config"
    # upload encrypted databases
    UPLOAD_DB = "upload_edb"
    # for search request
    TOKEN = "token"
    RESULT = "result"
    # for debug
    CONTROL = "control"

    # 多key检索
    MULTI_TOKEN = "multi_token"
    MULTI_RESULT = "multi_result"

    # 删除数据
    DELETE = "delete"
    DELETE_RESULT = "delete_result"

    # 更新数据
    UPDATE = "update"
    UPDATE_RESULT = "update_result"
