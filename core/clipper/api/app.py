"""FastAPI app factory (implemented in WP6)."""

from __future__ import annotations

from fastapi import FastAPI


def create_app(*, fixture_mode: bool = False, start_background: bool = True) -> FastAPI:
    raise NotImplementedError("WP6")
