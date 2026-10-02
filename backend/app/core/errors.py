import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.db.tenancy import NotFound
from app.llm.errors import LlmBudgetExhausted


class ErrorBody(BaseModel):
    code: str
    resume_id: uuid.UUID | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        *,
        delete_cookies: tuple[tuple[str, str], ...] = (),
        resume_id: uuid.UUID | None = None,
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.delete_cookies = delete_cookies
        self.resume_id = resume_id


def error_response(
    status_code: int, code: str, *, resume_id: uuid.UUID | None = None
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, resume_id=resume_id))
    return JSONResponse(body.model_dump(mode="json", exclude_none=True), status_code)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        response = error_response(exc.status_code, exc.code, resume_id=exc.resume_id)
        for name, path in exc.delete_cookies:
            response.delete_cookie(name, path=path)
        return response

    @app.exception_handler(NotFound)
    def handle_not_found(_: Request, __: NotFound) -> JSONResponse:
        return error_response(404, "not_found")

    @app.exception_handler(LlmBudgetExhausted)
    def handle_budget_exhausted(_: Request, exc: LlmBudgetExhausted) -> JSONResponse:
        return error_response(429, exc.code)
