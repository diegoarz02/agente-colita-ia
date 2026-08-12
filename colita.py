"""
Colita — asistente personal de Diego.

Arquitectura (ver el vault, carpeta COLITA):
  - El cerebro es Claude, via claude-agent-sdk.
  - Las herramientas son los servidores MCP que ya estan en ~/.claude.json.
  - La personalidad se carga desde el vault, no vive aqui.
  - Los limites son la funcion `autoridad()`: leer libre, actuar con permiso.
  - La memoria tiene dos capas: sesion por tema (corto plazo, aislada)
    y el vault (largo plazo, compartido entre temas).

Uso:
    python colita.py                 abre el tema "general"
    python colita.py tesis           abre o retoma el tema "tesis"
    python colita.py --temas         lista los temas abiertos
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import poderes
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    TextBlock,
    list_sessions,
    tag_session,
)

# --------------------------------------------------------------------------
# Rutas
# --------------------------------------------------------------------------

VAULT = Path(r"C:\Users\diego\Documents\Obsidian Vault\Claude Diego")
IDENTIDAD = VAULT / "COLITA" / "colita-identidad-y-limites.md"
AQUI = Path(__file__).parent

# Carpetas que Colita puede leer directamente del disco.
# Leer es libre; escribir en ellas sigue pasando por `autoridad()`.
CARPETAS = [
    Path(r"C:\Users\diego\Documents"),
    Path(r"C:\Users\diego\OneDrive\Documentos"),
    Path(r"C:\Users\diego\Downloads"),
]


# --------------------------------------------------------------------------
# Personalidad — se lee del vault para tener una sola fuente de verdad
# --------------------------------------------------------------------------

INSTRUCCIONES_OPERATIVAS = """
# Como operas

Hablas por voz: la aplicacion dice tus respuestas en voz alta automaticamente,
con voz neuronal. No tienes que hacer nada para eso y no debes mencionarlo.

Como te van a escuchar, escribe para ser leida EN VOZ ALTA: frases cortas, sin
listas largas, sin bloques de codigo salvo que te los pidan, sin rutas completas
en medio de una frase. Si tienes que dar una ruta o un comando, anunciala
("te dejo la ruta por escrito") en vez de dictarla entera.

Se breve. Dos o tres frases suele bastar. Si hace falta mas detalle, ofrecelo
antes de soltarlo.

Cuando busques algo en las notas de Diego, usa el servidor `obsidian-rag`.

Tienes acceso a las carpetas de Diego. Cuando te pida algo de sus archivos,
**usa tus poderes propios antes que Glob y Read**, que no saben donde mirar ni
abren PDF:

- `buscar_archivo`: lo busca en Documentos, Escritorio, Descargas, OneDrive y
  el vault, y te lo da ordenado por fecha. Uselo SIEMPRE antes de decir que no
  encuentras algo.
- `listar_carpeta`: que hay dentro. Entiende atajos: "documentos", "escritorio",
  "descargas", "vault", "colita", "onedrive".
- `abrir_carpeta`: se la abre en el Explorador, con el archivo seleccionado.
- `leer_documento`: PDF, Word, Excel, CSV y texto. `Read` no abre PDF ni Word;
  esto si.

Di siempre la ruta completa de lo que abriste, para que el pueda comprobarlo.

# Fuentes

Solo llevan fuentes las respuestas que salen de **buscar**: en la web, en el
vault, en sus documentos o en un archivo que abriste. Ahi si, siempre, porque
sin la fuente no puede comprobarte.

NO llevan fuentes las acciones ni la conversacion normal: subir el volumen,
poner musica, abrir una app, mirar el estado de la laptop, responder algo que
ya sabes. Poner "Fuentes: -" o citar de donde sacaste que ibas a subir el
volumen es ruido. Si no buscaste nada, no hay nada que citar.

Cuando si haya fuentes, van TODAS JUNTAS AL FINAL, bajo un encabezado
`## Fuentes`, una por linea. Nunca sueltas en medio del texto ni como [1].
Esto no es cosmetico: la aplicacion corta esa seccion antes de leer la
respuesta en voz alta —a Diego no se le dictan veinte enlaces— y le avisa de
que las tiene escritas. Si las mezclas con el texto, te las lee todas.

No las anuncies tu ("las fuentes son...", "aqui te dejo las fuentes"): la
aplicacion ya lo dice. Escribe el encabezado y la lista, sin presentacion.

# Tus poderes propios (servidor `colita`)

- `volumen`, `abrir_app`, `estado_maquina`: control de la laptop.
- `poner_musica`: **la unica forma correcta de poner musica o un video**. Abre
  YouTube en el navegador de siempre de Diego, con su sesion y su bloqueador.
  NO uses Playwright para poner musica: ese navegador arranca con un perfil
  limpio, sin su sesion ni su bloqueador, y acabas peleando con anuncios.
- `enlazar_en_moc`: despues de crear una nota, ENLAZALA. Una nota sin enlaces
  entrantes no se encuentra navegando y es como si no existiera.
- `salud_del_vault`: enlaces rotos y notas huerfanas. Pasalo tras anyadir varias.
- `nota_de_clase`: la nota de una clase del ciclo, con su plantilla.
- `portapapeles`: lee lo que Diego tiene copiado, o le copia algo largo para
  que lo pegue. Mas rapido que dictarle una ruta o un comando.
- `recordar_luego`: recordatorio HABLADO dentro de N minutos.
- `resumen_del_dia`: que se movio hoy — notas del vault y archivos tocados.
- `analizar_datos`: ejecuta Python con pandas, numpy, sklearn y matplotlib.
  Es tu herramienta principal para analisis, ETL y modelado. Usala en vez de
  describir lo que harias: hazlo y ensenya los numeros.
- `crear_excel` y `crear_html`: entregables para Diego. Los informes van en HTML.
- `guardar_en_vault`: TU MEMORIA A LARGO PLAZO. Ver abajo.

# Como creces

El vault de Obsidian es tu cerebro y crece contigo. Cuando aprendas algo que
Diego querria reencontrar dentro de seis meses — un metodo que funciono, una
decision con su porque, una leccion de un error, el resumen de un paper —
**ofrecele guardarlo** con `guardar_en_vault`, y guardalo si dice que si.

Reglas de tu cerebro, innegociables:
- Destila, no copies. Del PDF de una clase no entra el PDF: entra la nota de
  que aprendiste y cuando lo usarias.
- Una nota por idea. Nada de cajon de sastre.
- Enlaza con [[nombre-de-nota]] en cuanto veas relacion.
Si metes copias en vez de conocimiento destilado, la busqueda devuelve ruido y
empeoras al crecer.

Tu especialidad es ciencia de datos, pipelines de ETL, analisis, deep learning
e IA generativa. Ahi es donde Diego espera criterio tuyo, no solo ejecucion.

# Con quien hablas

Diego estudia Estadistica en la Facultad de Ciencias Matematicas de la UNMSM
y esta en su DECIMO ciclo — el ultimo. Sus clases empiezan el 2026-08-24 y
lleva seis cursos:

1. Proyecto de Tesis II — continua su tesis sobre percepcion de inseguridad
   con ENAPRES; este ciclo toca el analisis. MLP y RBF.
2. Analisis Bayesiano — mas alla de la inferencia clasica: regresion y modelos
   predictivos bayesianos.
3. Teoria de Respuesta al Item (TRI).
4. Consultoria Estadistica — estadistica avanzada y asesoria, con enfoque de IA.
5. Epidemiologia — de la estadistica clasica al deep learning y vision.
6. Mineria de Datos II.

Lo que espera de ti en lo academico: teoria solida y respaldada por fuentes
reales (libros y papers, no blogs), codigo con buenas practicas, y la
capacidad de traducir eso a alguien que no es tecnico. Ese ultimo punto no es
un extra: es lo que le van a pedir en consultoria y en la defensa de tesis.

Tienes notas de los seis cursos en el vault. Entra por `moc-ciclo-10-unmsm`
antes de buscar por carpetas, y usa `obsidian-rag` para lo demas.

# Como le hablas

No lo sermoneas. Es un profesional, no alguien a quien tutelar.

- Nada de advertencias que no pidio, disclaimers de relleno ni recordatorios
  sobre el uso responsable de nada.
- Si crees que una decision suya es peor, lo dices UNA VEZ, con el motivo, en
  una o dos frases. Si el mantiene lo suyo, se hace lo suyo y no lo vuelves a
  mencionar.
- Si te equivocas, lo corriges y sigues. Sin disculpas largas ni recuento de
  errores.
- Entre una respuesta segura y vacia y una util con sus supuestos dichos,
  siempre la util.

Cuando una accion caiga en la columna de "recomienda y espera el si", no la
ejecutes: describe que harias y por que, y pregunta. Si Diego dice que si,
ejecutala y confirma que quedo hecha.
"""


def cargar_personalidad() -> str:
    """La personalidad vive en el vault. Si no esta, Colita no arranca a ciegas."""
    if not IDENTIDAD.exists():
        raise SystemExit(
            f"No encuentro la nota de identidad:\n  {IDENTIDAD}\n"
            "Colita no arranca sin saber quien es."
        )
    return IDENTIDAD.read_text(encoding="utf-8") + INSTRUCCIONES_OPERATIVAS


# --------------------------------------------------------------------------
# La lista de autoridad, como codigo
#
# Esta funcion es la barrera real. El modelo puede ser convencido por contenido
# malicioso; esta funcion no. Ver `inyeccion-de-prompt-por-datos-de-terceros`.
# --------------------------------------------------------------------------

# Revisado el 2026-08-10 por peticion de Diego: preguntar por todo es engorroso.
# El permiso se reserva para lo excepcional — borrar, mandar fuera, tocar el
# sistema — no para leer ni para cosas reversibles.

# LIBRE: leer cualquier cosa, y escribir donde es reversible o inocuo.
LIBRE = {
    "Read", "Grep", "Glob", "WebFetch", "WebSearch", "NotebookRead",
    "TodoWrite", "Task", "Write", "Edit", "NotebookEdit",
}
LIBRE_PATRONES = (
    # lectura de cualquier MCP
    "search", "list", "get_", "read", "fetch", "query", "describe", "retrieve",
    "status", "similar", "context", "stats", "download", "browser_snapshot",
    "browser_navigate", "browser_take_screenshot", "browser_click",
    "browser_type", "browser_press_key", "browser_hover", "browser_wait",
    "browser_tabs", "browser_find", "browser_console", "browser_network",
    # Manejar una pagina ya abierta. Anyadido el 2026-08-12: pedir permiso para
    # `browser_evaluate` cuando lo unico que hacia era LEER si el video estaba
    # en pausa convertia "pon musica" en un interrogatorio. Dentro de una
    # pestanya que Diego pidio abrir, esto es manejar la pagina, no actuar
    # fuera. `browser_run_code_unsafe` y `browser_file_upload` siguen fuera:
    # el primero escapa del navegador y el segundo saca archivos de la maquina.
    "browser_evaluate", "browser_select_option", "browser_drag", "browser_drop",
    "browser_handle_dialog", "browser_resize", "browser_close",
    "browser_navigate_back",
    # voz, notas y volumen
    "speak", "tts", "note_save", "volumen", "volume", "brillo", "brightness",
    "abrir_app", "ventana", "window", "poner_musica",
    # el vault: crear y enlazar notas es reversible y es su trabajo
    "guardar_en_vault", "enlazar_en_moc", "salud_del_vault", "nota_de_clase",
    # mirar y abrir cosas de Diego: leer es libre, y abrir el Explorador o una
    # app no cambia nada. Ojo: "abrir_carpeta" no cae en CONFIRMAR porque no
    # contiene ninguno de esos patrones — es a proposito.
    "buscar_archivo", "listar_carpeta", "abrir_carpeta", "leer_documento",
    "portapapeles", "recordar_luego", "resumen_del_dia",
)

# CONFIRMAR: sale de la maquina, borra, o cambia el sistema.
CONFIRMAR_PATRONES = (
    "delete", "remove", "borrar", "trash", "archive", "send", "enviar",
    "post_", "create_event", "update_event", "publish", "deploy",
    "install", "uninstall", "share", "permission", "upload", "buy",
    "purchase", "pay", "move_pages", "rename",
)

# NUNCA.
PROHIBIDO_PATRONES = ("registry", "reg_write", "push --force", "reset --hard")

# Comandos de shell que se ejecutan sin preguntar (solo lectura / inocuos).
BASH_LIBRE = (
    "date", "ls ", "dir ", "cat ", "type ", "echo ", "pwd", "whoami",
    "git status", "git log", "git diff", "git branch", "--version", "-v",
    "python -c", "where ", "which ", "systeminfo", "tasklist",
)
BASH_PELIGRO = ("rm ", "del ", "rmdir", "format", "shutdown", "reg ", "diskpart", "-rf")


def _clasificar(tool: str, entrada: dict | None = None) -> str:
    t = tool.lower()

    if any(p in t for p in PROHIBIDO_PATRONES):
        return "prohibido"

    # El shell se juzga por el comando, no por el nombre de la herramienta.
    if t in {"bash", "powershell", "shell"}:
        cmd = str((entrada or {}).get("command", "")).lower()
        if any(p in cmd for p in BASH_PELIGRO):
            return "confirmar"
        if any(cmd.strip().startswith(p.strip()) or p in cmd for p in BASH_LIBRE):
            return "libre"
        return "confirmar"

    if any(p in t for p in CONFIRMAR_PATRONES):
        return "confirmar"
    if tool in LIBRE:
        return "libre"
    if t.startswith("mcp__") and any(p in t for p in LIBRE_PATRONES):
        return "libre"
    return "confirmar"


# Como se pide permiso. La terminal usa input(); el orbe lo sustituye por un
# dialogo. Sin esto, `input()` revienta bajo pythonw (no hay stdin) — que es
# exactamente el fallo que Diego vio.
def _preguntar_en_consola(tool: str, entrada: dict) -> bool:
    print(f"\n  [Colita quiere usar: {tool}]")
    resumen = str(entrada)
    print(f"  {resumen[:300]}{'...' if len(resumen) > 300 else ''}")
    try:
        return input("  Autorizo? (s/n): ").strip().lower().startswith("s")
    except (EOFError, OSError):
        print("  (sin consola disponible -> denegado por seguridad)")
        return False


pedir_permiso = _preguntar_en_consola   # el orbe reemplaza esto al arrancar


async def autoridad(tool_name, input_data, context):
    """Intercepta cada herramienta antes de ejecutarla."""
    nivel = _clasificar(tool_name, input_data)

    if nivel == "libre":
        return PermissionResultAllow(updated_input=input_data)

    if nivel == "prohibido":
        return PermissionResultDeny(
            message=(
                "Eso esta fuera de mis limites y no lo voy a hacer. "
                "Si de verdad hace falta, hazlo tu a mano."
            ),
            interrupt=True,
        )

    if pedir_permiso(tool_name, input_data):
        return PermissionResultAllow(updated_input=input_data)
    return PermissionResultDeny(
        message="Diego no lo autorizo. No insistas; sigue con lo demas."
    )


# --------------------------------------------------------------------------
# Memoria: una sesion por tema
#
# Corto plazo  -> la sesion del tema. Cambiar de tema NO cruza contextos.
# Largo plazo  -> el vault, accesible desde cualquier tema via obsidian-rag.
# --------------------------------------------------------------------------

PREFIJO = "colita:"


def sesion_del_tema(tema: str) -> str | None:
    """Devuelve el id de la sesion etiquetada con este tema, si existe."""
    etiqueta = f"{PREFIJO}{tema}"
    try:
        for s in list_sessions(directory=str(AQUI), limit=100):
            if getattr(s, "tag", None) == etiqueta:
                return s.session_id
    except Exception:
        pass  # primera ejecucion: todavia no hay historial
    return None


def listar_temas() -> None:
    try:
        sesiones = list_sessions(directory=str(AQUI), limit=100)
    except Exception:
        sesiones = []
    temas = [s for s in sesiones if (getattr(s, "tag", "") or "").startswith(PREFIJO)]
    if not temas:
        print("Todavia no hay temas abiertos.")
        return
    print("Temas abiertos:")
    for s in temas:
        print(f"  - {s.tag.removeprefix(PREFIJO):<20} {s.summary or '(sin resumen)'}")


# --------------------------------------------------------------------------
# Bucle principal
# --------------------------------------------------------------------------

def construir_opciones(tema: str) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        system_prompt=cargar_personalidad(),
        setting_sources=["user"],   # hereda los MCP y skills de ~/.claude.json
        skills="all",
        mcp_servers={"colita": poderes.servidor},   # sus poderes propios
        can_use_tool=autoridad,     # la lista de autoridad
        resume=sesion_del_tema(tema),
        cwd=str(AQUI),
        add_dirs=[str(p) for p in CARPETAS if p.exists()],
        permission_mode="default",
        model="claude-opus-5",
    )


async def conversar(tema: str) -> None:
    print(f"Colita — tema: {tema}")
    print("Escribe tu mensaje. 'salir' para terminar.\n")

    async with ClaudeSDKClient(options=construir_opciones(tema)) as colita:
        while True:
            try:
                mensaje = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not mensaje:
                continue
            if mensaje.lower() in {"salir", "chau", "adios"}:
                break

            await colita.query(mensaje)
            async for msg in colita.receive_response():
                if isinstance(msg, AssistantMessage):
                    for bloque in msg.content:
                        if isinstance(bloque, TextBlock):
                            print(bloque.text)
            print()

    # Etiquetar la sesion para poder retomar este tema manyana.
    try:
        recientes = list_sessions(directory=str(AQUI), limit=1)
        if recientes:
            tag_session(recientes[0].session_id, f"{PREFIJO}{tema}")
    except Exception as e:
        print(f"(aviso: no pude etiquetar la sesion: {e})")


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in {"--temas", "-t"}:
        listar_temas()
        return
    tema = args[0] if args else "general"
    asyncio.run(conversar(tema))


if __name__ == "__main__":
    main()
