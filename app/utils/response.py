from typing import Any, Optional, Dict, Union, List
from fastapi.responses import JSONResponse
import json
from datetime import datetime, date
from decimal import Decimal


def to_camel(string: str) -> str:
    """将蛇形命名转换为驼峰命名"""
    if not string:
        return string
    words = string.split('_')
    return words[0] + ''.join(word.capitalize() for word in words[1:])


def to_snake(string: str) -> str:
    """将驼峰命名转换为蛇形命名"""
    if not string:
        return string
    result = [string[0].lower()]
    for char in string[1:]:
        if char.isupper():
            result.extend(['_', char.lower()])
        else:
            result.append(char)
    return ''.join(result)


def dict_to_camel(data: Any) -> Any:
    """
    将字典键从蛇形转换为驼峰（递归处理）
    同时处理序列化
    """
    if data is None:
        return None
    elif isinstance(data, (str, int, float, bool)):
        return data
    elif isinstance(data, dict):
        result = {}
        for key, value in data.items():
            camel_key = to_camel(key)
            result[camel_key] = dict_to_camel(value)
        return result
    elif isinstance(data, list):
        return [dict_to_camel(item) for item in data]
    elif isinstance(data, (datetime, date)):
        return data.isoformat()
    elif isinstance(data, Decimal):
        return float(data)
    elif hasattr(data, '__dict__'):
        # 尝试获取对象的属性
        try:
            # 如果是 SQLAlchemy 模型
            if hasattr(data, '__table__'):
                result = {}
                for column in data.__table__.columns:
                    value = getattr(data, column.name)
                    result[to_camel(column.name)] = dict_to_camel(value)
                return result
            elif hasattr(data, 'model_dump'):
                # Pydantic 模型
                return dict_to_camel(data.model_dump())
            else:
                # 普通对象
                return dict_to_camel(data.__dict__)
        except:
            return str(data)
    elif hasattr(data, 'model_dump'):
        # Pydantic 模型（直接调用）
        return dict_to_camel(data.model_dump())
    else:
        return str(data)


def dict_to_snake(data: Any) -> Any:
    """
    将字典键从驼峰转换为蛇形（递归处理）
    用于请求参数处理
    """
    if data is None:
        return None
    elif isinstance(data, (str, int, float, bool)):
        return data
    elif isinstance(data, dict):
        result = {}
        for key, value in data.items():
            snake_key = to_snake(key)
            result[snake_key] = dict_to_snake(value)
        return result
    elif isinstance(data, list):
        return [dict_to_snake(item) for item in data]
    else:
        return data


def serialize_data(data: Any) -> Any:
    """
    序列化数据，处理 SQLAlchemy 对象和其他不可序列化的类型
    并转换为驼峰命名
    """
    return dict_to_camel(data)

#成功返回
def success_response(
        message: str = "success",
        data: Any = None,
        code: int = 200,
        **kwargs
) -> JSONResponse:
    """
    成功响应
    对应Java的 success 响应格式
    """
    # 序列化数据并转换为驼峰命名
    serialized_data = serialize_data(data)

    response_data = {
        "code": code,
        "message": message,
        "data": serialized_data
    }

    # 添加额外的参数
    if kwargs:
        # 将额外参数也转换为驼峰命名
        camel_kwargs = dict_to_camel(kwargs)
        response_data.update(camel_kwargs)

    return JSONResponse(
        status_code=200,
        content=response_data
    )

#失败返回
def error_response(
        message: str = "error",
        data: Any = None,
        code: int = 500,
        **kwargs
) -> JSONResponse:
    """
    错误响应
    对应Java的 error 响应格式
    """
    # 序列化数据并转换为驼峰命名
    serialized_data = serialize_data(data)

    response_data = {
        "code": code,
        "message": message,
        "data": serialized_data
    }

    # 添加额外的参数
    if kwargs:
        # 将额外参数也转换为驼峰命名
        camel_kwargs = dict_to_camel(kwargs)
        response_data.update(camel_kwargs)

    return JSONResponse(
        status_code=200,  # 为了与Java兼容，错误也返回200
        content=response_data
    )


def create_response(
        success: bool = True,
        message: str = "",
        data: Any = None,
        code: Optional[int] = None,
        **kwargs
) -> JSONResponse:
    """
    通用响应创建函数
    """
    if code is None:
        code = 200 if success else 500

    if success:
        return success_response(message, data, code, **kwargs)
    else:
        return error_response(message, data, code, **kwargs)


# 快速创建特定类型的响应
class ResponseFactory:
    """响应工厂类"""
    #操作成功
    @staticmethod
    def ok(data: Any = None, message: str = "success", **kwargs) -> JSONResponse:
        return success_response(message, data, 200, **kwargs)
    #创建成功
    @staticmethod
    def created(data: Any = None, message: str = "create success", **kwargs) -> JSONResponse:
        return success_response(message, data, 201, **kwargs)

    #请求已接受
    @staticmethod
    def accepted(message: str = "request is accepted", **kwargs) -> JSONResponse:
        return success_response(message, None, 202, **kwargs)

    #没有信息
    @staticmethod
    def no_content(message: str = "no message", **kwargs) -> JSONResponse:
        return success_response(message, None, 204, **kwargs)

    #参数错误
    @staticmethod
    def bad_request(message: str = "error", data: Any = None, **kwargs) -> JSONResponse:
        return error_response(message, data, 400, **kwargs)

    #授权失败
    @staticmethod
    def unauthorized(message: str = "unauthorized", data: Any = None, **kwargs) -> JSONResponse:
        return error_response(message, data, 401, **kwargs)

    #请求被禁止
    @staticmethod
    def forbidden(message: str = "forbidden", data: Any = None, **kwargs) -> JSONResponse:
        return error_response(message, data, 403, **kwargs)
    #找不到请求资源
    @staticmethod
    def not_found(message: str = "not_found", data: Any = None, **kwargs) -> JSONResponse:
        return error_response(message, data, 404, **kwargs)

    #资源冲突
    @staticmethod
    def conflict(message: str = "conflict", data: Any = None, **kwargs) -> JSONResponse:
        return error_response(message, data, 409, **kwargs)

    #服务器内部错误
    @staticmethod
    def internal_error(message: str = "service error", data: Any = None, **kwargs) -> JSONResponse:
        return error_response(message, data, 500, **kwargs)

    @staticmethod
    def custom(
            code: int,
            success: bool,
            message: str,
            data: Any = None,
            **kwargs
    ) -> JSONResponse:
        """自定义响应"""
        if success:
            return success_response(message, data, code, **kwargs)
        else:
            return error_response(message, data, code, **kwargs)


# 辅助函数：处理请求参数（从驼峰转蛇形）
def process_request_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    处理请求参数，将驼峰命名转换为蛇形命名
    用于在控制器中处理传入的请求参数
    """
    return dict_to_snake(params)


# 辅助函数：处理响应数据（从蛇形转驼峰）
def process_response_data(data: Any) -> Any:
    """
    处理响应数据，将蛇形命名转换为驼峰命名
    用于在控制器中处理返回的响应数据
    """
    return serialize_data(data)