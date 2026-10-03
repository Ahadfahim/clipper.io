"""Secrets in Windows Credential Manager (via ``keyring``), never in files or the repo.

On Windows ``keyring`` uses the WinVault backend (Credential Manager). Tests and Linux CI use an
in-memory backend installed by ``use_memory_backend()``.
"""

from __future__ import annotations

import contextlib

import keyring
from keyring.backend import KeyringBackend
from keyring.errors import KeyringError, PasswordDeleteError

SERVICE = "clipper.io"
SECRET_NAMES: tuple[str, ...] = ("discord_bot_token", "extension_pairing_token", "hf_token")


def get_secret(name: str) -> str | None:
    try:
        return keyring.get_password(SERVICE, name)
    except KeyringError:
        return None


def set_secret(name: str, value: str) -> None:
    if name not in SECRET_NAMES:
        raise KeyError(f"unknown secret {name!r}")
    keyring.set_password(SERVICE, name, value)


def delete_secret(name: str) -> None:
    with contextlib.suppress(PasswordDeleteError):
        keyring.delete_password(SERVICE, name)


class MemoryKeyring(KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self._store.pop((service, username), None)


def use_memory_backend() -> MemoryKeyring:
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    return backend
