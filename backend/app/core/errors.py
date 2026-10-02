from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.db.tenancy import NotFound


class ErrorBody(BaseModel):
    code: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        *,
        delete_cookies: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.delete_cookies = delete_cookies


def error_response(status_code: int, code: str) -> JSONResponse:
    return JSONResponse(ErrorResponse(error=ErrorBody(code=code)).model_dump(), status_code)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        response = error_response(exc.status_code, exc.code)
        for name, path in exc.delete_cookies:
            response.delete_cookie(name, path=path)
        return response

    @app.exception_handler(NotFound)
    def handle_not_found(_: Request, __: NotFound) -> JSONResponse:
        return error_response(404, "not_found")
