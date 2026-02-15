from __future__ import annotations

import os

from fastapi import Header, HTTPException, status


def check_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.getenv("GATEWAY_API_KEY")
    if not expected:
        return
    if x_api_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
