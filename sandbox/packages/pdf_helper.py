"""pdf-helper (harmlost demotillegg).

Later som det teller sider i et dokument. Leser én oppdiktet fil i den falske
hjemmemappen og regner på teksten. Ingen nettverk, ingen agnfiler.
"""

from __future__ import annotations

import os
from pathlib import Path


def run():
    doc = Path(os.path.expanduser("~")) / "Dokumenter" / "faktura-demo.txt"
    text = doc.read_text(encoding="utf-8")
    return {
        "fil": doc.name,
        "sider": text.count("\f") + 1,
        "tegn": len(text),
    }
