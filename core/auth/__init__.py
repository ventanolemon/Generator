"""Вход на сервер: обмен логина и пароля на токен сессии."""

from .client import AuthError, ServerAuthClient, login_to_server

__all__ = ["ServerAuthClient", "AuthError", "login_to_server"]
