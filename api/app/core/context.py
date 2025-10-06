from contextvars import ContextVar
from fastapi import Request

request_context: ContextVar[Request] = ContextVar("request_context")