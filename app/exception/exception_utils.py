# app/utils/exception_utils.py
import traceback
import logging
import sys
import os
from typing import Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


def format_traceback_for_ide(exc: Exception) -> str:
    """
    格式化异常信息，使其在IDE中可以点击跳转

    Args:
        exc: 异常对象

    Returns:
        格式化的可点击异常信息字符串
    """
    exc_type = exc.__class__.__name__
    exc_tb = exc.__traceback__

    # 获取异常的堆栈跟踪
    tb_frames = traceback.extract_tb(exc_tb)

    if not tb_frames:
        return f"{exc_type}: {str(exc)}"

    lines = []

    # 首先显示最直接的错误位置（最后发生的）
    last_frame = tb_frames[-1]
    # 格式化为：文件名:行号:函数名
    # 这是PyCharm/VSCode都能识别的格式
    location = f"  File \"{last_frame.filename}\", line {last_frame.lineno}, in {last_frame.name}"
    lines.append(location)

    # 显示具体代码行（如果存在）
    if last_frame.line:
        lines.append(f"    {last_frame.line.strip()}")

    # 添加异常类型和消息
    lines.append(f"{exc_type}: {str(exc)}")

    # 添加调用栈（前5层，从最近到最远）
    if len(tb_frames) > 1:
        lines.append("\nCall stack (最近调用在前):")
        # 取最近的几个调用帧（不包括已经显示的最后一个）
        for i, frame in enumerate(reversed(tb_frames[-6:-1])):
            lines.append(f"  [{i + 1}] File \"{frame.filename}\", line {frame.lineno}, in {frame.name}")
            if frame.line:
                lines.append(f"      {frame.line.strip()}")

    return "\n".join(lines)


def get_exception_summary(exc: Exception) -> dict:
    """
    获取异常摘要信息

    Args:
        exc: 异常对象

    Returns:
        异常摘要字典
    """
    exc_type = exc.__class__.__name__
    exc_tb = exc.__traceback__

    summary = {
        "exception_type": exc_type,
        "exception_message": str(exc),
        "timestamp": datetime.now().isoformat(),
    }

    if exc_tb:
        tb_frames = traceback.extract_tb(exc_tb)
        if tb_frames:
            last_frame = tb_frames[-1]
            summary.update({
                "file": last_frame.filename,
                "line": last_frame.lineno,
                "function": last_frame.name,
                "code_snippet": last_frame.line if last_frame.line else None,
                "stack_depth": len(tb_frames),
            })

    return summary

def printError(exc: Exception):
    log_exception_with_clickable_trace(
        exc,
        context="",
        level=logging.ERROR
    )

def log_exception_with_clickable_trace(
        exc: Exception,
        context: str = "",
        logger_instance: Optional[logging.Logger] = None,
        level: int = logging.ERROR
):
    """
    记录异常信息，包含可点击的跟踪信息

    Args:
        exc: 异常对象
        context: 上下文描述
        logger_instance: 使用的logger实例，默认为模块logger
        level: 日志级别，默认为ERROR
    """
    log = logger_instance if logger_instance else logger

    # 获取可点击格式的异常信息
    formatted_trace = format_traceback_for_ide(exc)

    # 获取异常摘要
    summary = get_exception_summary(exc)

    # 构建日志消息
    if context:
        log_message = f"[{context}] 发生异常"
    else:
        log_message = "发生异常"

    # 记录摘要信息
    log.log(level, f"{log_message}: {summary['exception_type']} - {summary['exception_message']}")

    # 记录详细位置信息（可点击格式）
    log.log(level, f"位置: {summary.get('file', '未知文件')}:{summary.get('line', '未知行号')}")
    if summary.get('code_snippet'):
        log.log(level, f"代码: {summary['code_snippet']}")

    # 记录完整的可点击跟踪信息
    log.log(level, f"详细跟踪信息:\n{formatted_trace}")

    # 如果是在调试模式，还可以输出更详细的堆栈信息
    if logger.isEnabledFor(logging.DEBUG):
        full_traceback = traceback.format_exception(type(exc), exc, exc.__traceback__)
        log.debug("完整异常堆栈:")
        for line in full_traceback:
            for subline in line.split('\n'):
                if subline.strip():
                    log.debug(subline)


def log_function_error(
        func,
        exc: Exception,
        args: tuple = None,
        kwargs: dict = None,
        logger_instance: Optional[logging.Logger] = None
):
    """
    记录函数执行时的异常信息

    Args:
        func: 函数对象
        exc: 异常对象
        args: 函数参数
        kwargs: 函数关键字参数
        logger_instance: 使用的logger实例
    """
    log = logger_instance if logger_instance else logger

    # 获取函数名和位置信息
    func_name = func.__name__ if hasattr(func, '__name__') else str(func)
    func_module = func.__module__ if hasattr(func, '__module__') else "未知模块"

    # 格式化参数信息
    args_str = ""
    if args:
        args_str = ", ".join([repr(arg) for arg in args])
    if kwargs:
        kwargs_str = ", ".join([f"{k}={repr(v)}" for k, v in kwargs.items()])
        if args_str:
            args_str = f"{args_str}, {kwargs_str}"
        else:
            args_str = kwargs_str

    context = f"函数 {func_module}.{func_name}({args_str})"
    log_exception_with_clickable_trace(exc, context, log)


class ExceptionContext:
    """
    异常上下文管理器，用于捕获代码块中的异常
    """

    def __init__(self, context: str = "", re_raise: bool = True, logger_instance: Optional[logging.Logger] = None):
        self.context = context
        self.re_raise = re_raise
        self.logger = logger_instance if logger_instance else logger
        self.exception = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val:
            self.exception = exc_val
            log_exception_with_clickable_trace(exc_val, self.context, self.logger)

            if self.re_raise:
                return False  # 重新抛出异常
            else:
                return True  # 不重新抛出异常
        return True


# 使用示例装饰器
def log_exceptions(logger_instance: Optional[logging.Logger] = None, re_raise: bool = True):
    """
    异常日志装饰器

    Args:
        logger_instance: 使用的logger实例
        re_raise: 是否重新抛出异常
    """

    def decorator(func):
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                log_function_error(func, e, args, kwargs, logger_instance)
                if re_raise:
                    raise

        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                log_function_error(func, e, args, kwargs, logger_instance)
                if re_raise:
                    raise

        if hasattr(func, '__code__') and hasattr(func.__code__, 'co_flags'):
            # 检查是否是异步函数
            import inspect
            if inspect.iscoroutinefunction(func):
                return async_wrapper
        return sync_wrapper

    return decorator