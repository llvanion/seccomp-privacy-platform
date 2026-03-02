# -*- coding:utf-8 _*-
""" 
LIB-SSE CODE
@author: Jeza Chen
@license: GPL-3.0 License
@file: logger.py 
@time: 2022/03/18
@contact: jeza@vip.qq.com
@site:  
@software: PyCharm 
@description: logging
"""
import logging
import pathlib
import time

__logger_cache = {}
_PROGRAM_DIR_PATH = pathlib.Path.home().joinpath(".sse")
_LOG_DIR_PATH = _PROGRAM_DIR_PATH.joinpath("log")
if not _LOG_DIR_PATH.exists():
    _LOG_DIR_PATH.mkdir(parents=True)


def getSSELogger(logger_name="sse", console_log_level=logging.INFO, file_log_level=logging.INFO):
    if logger_name in __logger_cache:
        return __logger_cache[logger_name]

    logger = logging.getLogger(logger_name)

    logger.setLevel(logging.DEBUG)  # 支持DEBUG级别

    # 1. Console
    sh = logging.StreamHandler()
    sh.setLevel(console_log_level)
    # 2. File
    rq = time.strftime('%Y-%m-%d-%H-%M-%S', time.localtime((time.time())))
    log_name = logger_name + '_' + rq + '.log'
    log_path = _LOG_DIR_PATH.joinpath(log_name)
    fh = logging.FileHandler(log_path)
    fh.setLevel(file_log_level)

    # Format，毫秒级日志
    formatter = logging.Formatter("[%(asctime)s.%(msecs)03d][%(filename)s-->line:%(lineno)d][%(levelname)s] %(message)s", datefmt='%Y-%m-%d %H:%M:%S')
    sh.setFormatter(formatter)
    fh.setFormatter(formatter)

    # add handler
    logger.addHandler(fh)
    logger.addHandler(sh)

    __logger_cache[logger_name] = logger
    return logger
