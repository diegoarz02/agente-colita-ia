"""
Registro de Colita.

Por que existe: `orbe.py` corre bajo `pythonw.exe`, que no tiene consola. Ahi
`sys.stdout` es None y **todos los `print` se pierden en silencio**. Durante una
sesion entera Diego no pudo ver por que el despertador no se activaba, porque no
habia donde mirar.

Todo lo que antes era `print` ahora va a `colita\\registro.log`, con hora y con
la traza completa cuando algo revienta. Para verlo en vivo:

    Get-Content C:\\Users\\diego\\colita\\registro.log -Wait -Tail 30
"""

from __future__ import annotations

import datetime as _dt
import threading
import traceback
from pathlib import Path

ARCHIVO = Path(__file__).parent / "registro.log"
LIMITE = 2_000_000          # 2 MB: se rota solo, no crece sin fin

_candado = threading.Lock()


def _rotar() -> None:
    try:
        if ARCHIVO.exists() and ARCHIVO.stat().st_size > LIMITE:
            ARCHIVO.replace(ARCHIVO.with_suffix(".log.viejo"))
    except Exception:
        pass


def log(mensaje: str, etiqueta: str = "colita") -> None:
    """Escribe una linea. Nunca lanza: un fallo del log no puede tumbar a Colita."""
    try:
        hora = _dt.datetime.now().strftime("%H:%M:%S")
        linea = f"{hora} [{etiqueta}] {mensaje}\n"
        with _candado:
            _rotar()
            with open(ARCHIVO, "a", encoding="utf-8") as f:
                f.write(linea)
    except Exception:
        pass


def fallo(mensaje: str, etiqueta: str = "colita") -> None:
    """Como `log`, pero adjunta la traza del error que se este manejando."""
    log(f"{mensaje}\n{traceback.format_exc()}", etiqueta)


def arranque(que: str) -> None:
    try:
        with _candado:
            with open(ARCHIVO, "a", encoding="utf-8") as f:
                sello = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"\n{'=' * 60}\n{sello}  arranca {que}\n{'=' * 60}\n")
    except Exception:
        pass
