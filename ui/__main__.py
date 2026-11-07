"""Starter nettsiden. Bruk: python -m ui"""

from __future__ import annotations

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "ui.app:app",
        host=os.environ.get("LONEWATCH_HOST", "127.0.0.1"),
        port=int(os.environ.get("LONEWATCH_PORT", "8000")),
        reload=False,
    )
