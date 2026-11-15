"""OpenAI 兼容的网关错误响应"""
from fastapi.responses import JSONResponse


def gateway_error_response(
        status_code: int,
        message: str,
        *,
        error_type: str = "invalid_request_error",
        code: str | None = None,
        headers: dict | None = None,
) -> JSONResponse:
    error = {"message": message, "type": error_type}
    if code:
        error["code"] = code
    return JSONResponse(
        status_code=status_code,
        content={"error": error},
        headers=headers or {},
    )
