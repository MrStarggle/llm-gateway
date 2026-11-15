from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from typing import Union
import traceback
import logging

logger = logging.getLogger(__name__)


# 定义自定义异常类（可选）
class BusinessException(Exception):
    """业务异常"""

    def __init__(self, code: int = 500, message: str = "业务异常", data: any = None):
        self.code = code
        self.message = message
        self.data = data


class ValidationException(Exception):
    """验证异常"""

    def __init__(self, message: str = "参数验证失败", errors: list = None):
        self.message = message
        self.errors = errors


# 全局异常处理器
async def global_exception_handler(request: Request, exc: Exception):
    """
    全局异常处理器
    统一返回Java风格的响应格式
    """
    # 获取异常信息
    error_detail = str(exc)
    exc_traceback = traceback.format_exc()

    # 根据异常类型设置响应码和消息
    if isinstance(exc, BusinessException):
        status_code = 200
        code = exc.code
        message = exc.message
        data = exc.data
        logger.warning(f"业务异常: {code} - {message}")

    elif isinstance(exc, ValidationException):
        status_code = 200
        code = 400
        message = exc.message
        data = {"errors": exc.errors} if exc.errors else None
        logger.warning(f"参数验证失败: {exc.message}")

    elif isinstance(exc, RequestValidationError):
        status_code = 200
        code = 422
        # 提取验证错误详情
        validation_errors = []
        for error in exc.errors():
            validation_errors.append({
                "field": " -> ".join(str(loc) for loc in error.get("loc", [])),
                "message": error.get("msg", ""),
                "type": error.get("type", ""),
            })
        message = "请求参数验证失败"
        data = {"errors": validation_errors}
        logger.warning(
            f"请求参数验证失败: {request.method} {request.url.path} | "
            + " | ".join(e["field"] + ": " + e["message"] for e in validation_errors)
        )

    elif isinstance(exc, (HTTPException, StarletteHTTPException)):
        status_code = 200
        code = exc.status_code
        message = exc.detail
        data = getattr(exc, 'data', None)
        # 401/403 是预期的认证失败，降为 info；其他为 warning
        if code in (401, 403):
            logger.info(f"HTTP {code}: {request.method} {request.url.path}")
        else:
            logger.warning(f"HTTP异常: {code} - {message} - {request.method} {request.url.path}")

    else:
        status_code = 200
        code = 500
        message = "服务器内部错误"
        data = None

        # 对于未捕获的异常，记录更详细的上下文信息
        logger.error(f"未捕获异常类型: {exc.__class__.__name__}")
        logger.error(f"异常模块: {exc.__class__.__module__}")

    # 构建响应
    response_data = {
        "code": code,
        "message": message,
        "data": data
    }

    # 如果是调试模式，添加异常详情
    if hasattr(request.app.state, "DEBUG") and request.app.state.DEBUG:
        response_data["detail"] = error_detail
        response_data["traceback"] = exc_traceback
        response_data["exception_type"] = exc.__class__.__name__

    return JSONResponse(
        status_code=status_code,
        content=response_data
    )