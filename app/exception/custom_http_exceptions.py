from fastapi import HTTPException
from typing import Any, Optional


class CustomHTTPException(HTTPException):
    """自定义HTTP异常，兼容Java响应格式"""

    def __init__(
            self,
            status_code: int = 500,
            detail: str = None,
            headers: Optional[dict] = None,
            code: int = None,
            data: Any = None
    ):
        # 如果没有指定code，使用status_code
        if code is None:
            code = status_code

        # 如果没有指定detail，使用默认消息
        if detail is None:
            detail = self._get_default_message(status_code)

        super().__init__(status_code=status_code, detail=detail, headers=headers)

        # 添加额外属性
        self.code = code
        self.data = data

    @staticmethod
    def _get_default_message(status_code: int) -> str:
        """根据状态码获取默认消息"""
        messages = {
            200: "成功",
            400: "请求参数错误",
            401: "未授权",
            403: "禁止访问",
            404: "资源不存在",
            422: "参数验证失败",
            500: "服务器内部错误",
            502: "网关错误",
            503: "服务不可用",
        }
        return messages.get(status_code, "未知错误")


# 预定义的常用异常
class BadRequestException(CustomHTTPException):
    def __init__(self, detail: str = None, code: int = 400, data: Any = None):
        super().__init__(status_code=400, detail=detail, code=code, data=data)


class UnauthorizedException(CustomHTTPException):
    def __init__(self, detail: str = "未授权", code: int = 401, data: Any = None):
        super().__init__(status_code=401, detail=detail, code=code, data=data)


class ForbiddenException(CustomHTTPException):
    def __init__(self, detail: str = "禁止访问", code: int = 403, data: Any = None):
        super().__init__(status_code=403, detail=detail, code=code, data=data)


class NotFoundException(CustomHTTPException):
    def __init__(self, detail: str = "资源不存在", code: int = 404, data: Any = None):
        super().__init__(status_code=404, detail=detail, code=code, data=data)


class ValidationException(CustomHTTPException):
    def __init__(self, detail: str = "参数验证失败", errors: list = None, code: int = 422):
        data = {"errors": errors} if errors else None
        super().__init__(status_code=422, detail=detail, code=code, data=data)


class InternalServerErrorException(CustomHTTPException):
    def __init__(self, detail: str = "服务器内部错误", code: int = 500, data: Any = None):
        super().__init__(status_code=500, detail=detail, code=code, data=data)