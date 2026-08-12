"""
Poderes propios de Colita.

Herramientas que no existen en ningun MCP y que necesita para su trabajo:
control del sistema, guardar en el vault, y producir entregables (Excel, HTML).

Se exponen como un servidor MCP en proceso, asi que pasan por `autoridad()`
igual que todo lo demas.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

VAULT = Path(r"C:\Users\diego\Documents\Obsidian Vault\Claude Diego")
SALIDAS = Path(r"C:\Users\diego\colita\salidas")
SALIDAS.mkdir(exist_ok=True)

# Sin esto, cada subproceso abre una consola negra encima de lo que estes
# haciendo. Es la causa de las "pantallas negras" que aparecen y a veces se
# quedan. Todo subprocess de este archivo lo lleva.
SIN_VENTANA = {}
if os.name == "nt":
    _si = subprocess.STARTUPINFO()
    _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _si.wShowWindow = 0  # SW_HIDE
    SIN_VENTANA = {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": _si,
    }


def _ok(texto: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": texto}]}


def _slug(texto: str) -> str:
    s = re.sub(r"[^\w\s-]", "", texto.lower()).strip()
    return re.sub(r"[\s_]+", "-", s)[:60] or "sin-titulo"


# ══════════════════════════════════════════════════════ sistema

@tool("volumen", "Sube, baja o silencia el volumen de Windows. accion: subir|bajar|silenciar",
      {"accion": str})
async def volumen(args: dict[str, Any]) -> dict[str, Any]:
    teclas = {"subir": 0xAF, "bajar": 0xAE, "silenciar": 0xAD}
    accion = str(args.get("accion", "")).lower()
    if accion not in teclas:
        return _ok("Acción no válida. Usa subir, bajar o silenciar.")
    import ctypes
    for _ in range(1 if accion == "silenciar" else 5):
        ctypes.windll.user32.keybd_event(teclas[accion], 0, 0, 0)
        ctypes.windll.user32.keybd_event(teclas[accion], 0, 2, 0)
    return _ok(f"Volumen: {accion}.")


@tool("abrir_app", "Abre una aplicación o archivo de Windows por su nombre o ruta.",
      {"que": str})
async def abrir_app(args: dict[str, Any]) -> dict[str, Any]:
    que = str(args.get("que", "")).strip()
    if not que:
        return _ok("Dime qué abrir.")
    try:
        os.startfile(que)          # nombre de app, ruta o URL
        return _ok(f"Abierto: {que}")
    except Exception:
        try:
            subprocess.Popen(["cmd", "/c", "start", "", que], shell=False, **SIN_VENTANA)
            return _ok(f"Abierto: {que}")
        except Exception as e:
            return _ok(f"No pude abrir «{que}»: {e}")


@tool("estado_maquina", "Uso de CPU, memoria y disco de la laptop.", {})
async def estado_maquina(args: dict[str, Any]) -> dict[str, Any]:
    import psutil
    cpu = psutil.cpu_percent(interval=0.4)
    m = psutil.virtual_memory()
    d = psutil.disk_usage("C:\\")
    return _ok(
        f"CPU {cpu:.0f}% | RAM {m.percent:.0f}% ({m.used/1e9:.1f} de {m.total/1e9:.1f} GB) "
        f"| Disco C: {d.percent:.0f}% ({d.free/1e9:.0f} GB libres)"
    )


# ══════════════════════════════════════════════════════ cerebro (vault)

@tool(
    "guardar_en_vault",
    "Guarda conocimiento nuevo en el vault de Obsidian de Diego, para que no se pierda. "
    "carpeta: metodos|conceptos|aprendizajes|papers|proyectos|snippets",
    {"titulo": str, "carpeta": str, "contenido": str, "tags": str},
)
async def guardar_en_vault(args: dict[str, Any]) -> dict[str, Any]:
    carpetas = {"metodos", "conceptos", "aprendizajes", "papers", "proyectos", "snippets"}
    carpeta = str(args.get("carpeta", "conceptos")).lower()
    if carpeta not in carpetas:
        carpeta = "conceptos"

    titulo = str(args.get("titulo", "")).strip()
    if not titulo:
        return _ok("Necesito un título para la nota.")

    tipo = {"metodos": "metodo", "conceptos": "concepto", "aprendizajes": "aprendizaje",
            "papers": "paper", "proyectos": "proyecto", "snippets": "snippet"}[carpeta]
    tags = str(args.get("tags", "")).strip()
    lista = ", ".join(t.strip() for t in tags.split(",") if t.strip()) or tipo
    hoy = dt.date.today().isoformat()

    ruta = VAULT / carpeta / f"{_slug(titulo)}.md"
    if ruta.exists():
        return _ok(f"Ya existe esa nota: {ruta.name}. Léela y actualízala en vez de duplicar.")

    ruta.write_text(
        f"---\ntipo: {tipo}\ncreado: {hoy}\ntags: [{lista}]\n---\n\n"
        f"# {titulo}\n\n{args.get('contenido', '').strip()}\n",
        encoding="utf-8",
    )
    return _ok(f"Guardado en {carpeta}/{ruta.name}. Recuerda enlazarlo desde el MOC que toque.")


@tool("reindexar_vault", "Reconstruye el índice de búsqueda del vault tras añadir notas.", {})
async def reindexar_vault(args: dict[str, Any]) -> dict[str, Any]:
    uvx = Path(os.environ["LOCALAPPDATA"]) / "Microsoft/WinGet/Links/uvx.exe"
    entorno = {
        **os.environ,
        "OBSIDIAN_RAG_VAULT": str(VAULT),
        "OBSIDIAN_RAG_PROVIDER": "ollama",
        "OBSIDIAN_RAG_MODEL": "nomic-embed-text",
        "OBSIDIAN_RAG_OLLAMA_URL": "http://127.0.0.1:11434",
    }
    try:
        r = subprocess.run(
            [str(uvx), "--with", "mcp<2", "obsidian-notes-rag", "index"],
            env=entorno, capture_output=True, text=True, timeout=900, **SIN_VENTANA,
        )
        linea = next((l for l in r.stdout.splitlines() if "Indexed" in l), "reindexado")
        return _ok(linea.strip())
    except Exception as e:
        return _ok(f"No pude reindexar: {e}")


# ══════════════════════════════════════════════════════ entregables

@tool(
    "crear_excel",
    "Crea un .xlsx a partir de datos. filas: lista de listas en JSON, la primera es la cabecera.",
    {"nombre": str, "filas_json": str, "hoja": str},
)
async def crear_excel(args: dict[str, Any]) -> dict[str, Any]:
    import json
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    try:
        filas = json.loads(str(args.get("filas_json", "[]")))
    except Exception as e:
        return _ok(f"El JSON de filas no es válido: {e}")
    if not filas:
        return _ok("No me diste datos.")

    wb = Workbook()
    ws = wb.active
    ws.title = str(args.get("hoja", "Datos"))[:31]
    for f in filas:
        ws.append(list(f))

    cab = Font(bold=True, color="FFFFFF")
    relleno = PatternFill("solid", fgColor="1F3B5C")
    for c in ws[1]:
        c.font, c.fill = cab, relleno
    for col in ws.columns:
        ancho = max((len(str(c.value)) for c in col if c.value), default=8)
        ws.column_dimensions[col[0].column_letter].width = min(ancho + 3, 55)
    ws.freeze_panes = "A2"

    ruta = SALIDAS / f"{_slug(str(args.get('nombre', 'datos')))}.xlsx"
    wb.save(ruta)
    return _ok(f"Excel creado: {ruta}")


@tool(
    "crear_html",
    "Crea un informe HTML autocontenido, oscuro y legible. El cuerpo va en HTML.",
    {"titulo": str, "cuerpo_html": str},
)
async def crear_html(args: dict[str, Any]) -> dict[str, Any]:
    titulo = str(args.get("titulo", "Informe")).strip()
    ruta = SALIDAS / f"{_slug(titulo)}.html"
    ruta.write_text(
        "<!doctype html><html lang=es><meta charset=utf-8>"
        f"<title>{titulo}</title><style>"
        ":root{color-scheme:dark}"
        "body{background:#0a0e16;color:#dce6f5;font:16px/1.7 'Segoe UI',system-ui,sans-serif;"
        "max-width:860px;margin:0 auto;padding:48px 24px}"
        "h1{font-size:1.9rem;letter-spacing:-.02em;background:linear-gradient(92deg,#00e5ff,#8b5cff);"
        "-webkit-background-clip:text;background-clip:text;color:transparent}"
        "h2{margin-top:2.2em;color:#00e5ff;font-size:1.25rem}"
        "table{border-collapse:collapse;width:100%;margin:1.4em 0}"
        "th,td{border:1px solid #1e2a40;padding:9px 13px;text-align:left}"
        "th{background:#101a2b;color:#8fb4d9}tr:nth-child(even) td{background:#0d1420}"
        "code{background:#101a2b;padding:2px 6px;border-radius:4px;color:#00ff9d}"
        "pre{background:#0d1420;padding:16px;border-radius:10px;overflow-x:auto;"
        "border:1px solid #1e2a40}"
        "a{color:#00e5ff}.pie{margin-top:3em;color:#5b6b84;font-size:.85rem;"
        "border-top:1px solid #1e2a40;padding-top:1em}"
        f"</style><h1>{titulo}</h1>{args.get('cuerpo_html', '')}"
        f"<p class=pie>Generado por Colita AI · {dt.date.today().isoformat()}</p></html>",
        encoding="utf-8",
    )
    return _ok(f"Informe creado: {ruta}")


@tool(
    "analizar_datos",
    "Ejecuta código Python de análisis (pandas, numpy, sklearn, matplotlib) y devuelve la salida. "
    "Usa print() para lo que quieras ver. Las figuras se guardan en salidas/.",
    {"codigo": str},
)
async def analizar_datos(args: dict[str, Any]) -> dict[str, Any]:
    import sys
    import textwrap

    codigo = textwrap.dedent(str(args.get("codigo", "")))
    envoltorio = (
        "import matplotlib\nmatplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt, pandas as pd, numpy as np, os\n"
        f"os.chdir(r'{SALIDAS}')\n" + codigo + "\n"
        "for i in plt.get_fignums():\n"
        "    plt.figure(i).savefig(f'figura_{i}.png', dpi=140, bbox_inches='tight')\n"
    )
    try:
        r = subprocess.run(
            [sys.executable, "-c", envoltorio],
            capture_output=True, text=True, timeout=300, cwd=str(SALIDAS),
            **SIN_VENTANA,
        )
    except subprocess.TimeoutExpired:
        return _ok("El análisis tardó más de 5 minutos y lo corté.")

    salida = (r.stdout or "").strip()
    error = (r.stderr or "").strip()
    if error and r.returncode != 0:
        return _ok(f"Falló:\n{error[-1500:]}")
    return _ok(salida[-4000:] or "Se ejecutó sin imprimir nada.")


# ══════════════════════════════════════════════════════

servidor = create_sdk_mcp_server(
    name="colita",
    version="1.0.0",
    tools=[
        volumen, abrir_app, estado_maquina,
        guardar_en_vault, reindexar_vault,
        crear_excel, crear_html, analizar_datos,
    ],
)

NOMBRES = [
    "mcp__colita__volumen", "mcp__colita__abrir_app", "mcp__colita__estado_maquina",
    "mcp__colita__guardar_en_vault", "mcp__colita__reindexar_vault",
    "mcp__colita__crear_excel", "mcp__colita__crear_html", "mcp__colita__analizar_datos",
]
