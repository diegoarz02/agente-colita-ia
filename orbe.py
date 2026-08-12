"""
Colita — la bolita flotante.

Una ventana sin marco, transparente y siempre encima. Clic en el orbe para
abrir el panel; escribe y Colita responde (y lo dice en voz alta).

El cerebro es el mismo de `colita.py`: misma personalidad, mismos MCP, misma
lista de autoridad. Aqui solo esta la cara.

    C:\\venvs\\colita\\Scripts\\pythonw.exe C:\\Users\\diego\\colita\\orbe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
import time
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Ninguna ventana negra. NUNCA.
#
# Arreglar solo mis subprocess no bastaba: el Agent SDK lanza la CLI de Claude
# (node) por su cuenta, y esa era la consola que seguia apareciendo. La unica
# forma de taparlas todas — las mias, las del SDK y las de cualquier libreria —
# es poner el flag por defecto en Popen, antes de importar nada mas.
# ─────────────────────────────────────────────────────────────────────────────
if os.name == "nt":
    # ── LA SOLUCION BUENA ────────────────────────────────────────────────
    # El problema de raiz: pythonw.exe corre SIN consola. Cuando un hijo es
    # una app de consola (node, uvx, git...), Windows le crea una ventana
    # nueva porque no hay ninguna que heredar.
    #
    # Forzar CREATE_NO_WINDOW sobre el hijo lo rompe: le quita la consola de
    # control y muere con SIGHUP (el exit 129 que vio Diego).
    #
    # Lo correcto es al reves: darle al PADRE una consola y esconderla. Los
    # hijos la heredan, no crean ninguna, y sus tuberias siguen intactas.
    import ctypes

    try:
        k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
        if k32.GetConsoleWindow() == 0:      # pythonw: no hay consola
            k32.AllocConsole()
        hwnd = k32.GetConsoleWindow()
        if hwnd:
            u32.ShowWindow(hwnd, 0)          # SW_HIDE
    except Exception:
        pass

    # ── Que Windows la trate como una APP, no como "un Python" ───────────
    #
    # En la barra de tareas salia el icono de archivo de Python y se agrupaba
    # con cualquier otro script. El motivo: sin AppUserModelID propio, Windows
    # identifica la ventana por su ejecutable, que es `pythonw.exe`.
    #
    # Declarar un identificador propio la separa en su propia entrada, con su
    # icono, y permite anclarla a la barra de tareas como cualquier programa.
    # TIENE que hacerse antes de crear ninguna ventana.
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Diego.Colita.IA.1")
    except Exception:
        pass

    _Popen = subprocess.Popen

    class _PopenSilencioso(_Popen):
        """Solo esconde la ventana; NO usa CREATE_NO_WINDOW.

        Con la consola oculta del padre ya heredada, basta con pedirle a
        Windows que no muestre la ventana del hijo. Sin tocar creationflags
        las tuberias del SDK siguen funcionando.
        """

        def __init__(self, *a, **kw):
            if kw.get("startupinfo") is None:
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = 0  # SW_HIDE
                kw["startupinfo"] = si
            super().__init__(*a, **kw)

    subprocess.Popen = _PopenSilencioso

    # NO tocar asyncio.create_subprocess_exec.
    #
    # Lo intente el 2026-08-11 para tapar las consolas del SDK y rompio Colita:
    # "Command failed with exit code 129". El 129 es SIGHUP — al forzar
    # CREATE_NO_WINDOW sobre el proceso de la CLI, las tuberias de stdio con
    # las que el SDK se comunica se quedan sin consola de control y el hijo
    # muere en cuanto intenta hablar.
    #
    # Una Colita fea que funciona vale mas que una elegante que no responde.
    # Las consolas del SDK se atacan por otro lado (ver la nota del vault).

import webview
from pynput import keyboard

from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, TextBlock

import colita       # reutiliza personalidad, autoridad y sesiones por tema
import voz          # hablar() y escuchar()
import despertador  # la palabra de activacion
from registro import arranque, fallo, log

AQUI = Path(__file__).parent
# Marca de "cerrada a proposito". La escribe la ✕ y la borra cualquier arranque
# manual. Solo el vigilante la respeta.
DESCANSO = AQUI / "descansando.flag"
# 470 y no 400: con siete accesos rápidos la fila se parte en dos y la de abajo
# quedaba cortada por el borde de la ventana. La altura tiene que dar para el
# orbe, los medidores, el estado, DOS filas de botones y el pie.
CHICO = (480, 470)   # panel de mando: orbe, reloj, medidores, accesos
GRANDE = (560, 820)  # + la conversacion
ENORME = (820, 1000)  # para leer respuestas largas sin bizquear


class Cerebro:
    """Mantiene un ClaudeSDKClient vivo en su propio hilo con su bucle asyncio."""

    def __init__(self, tema: str = "general"):
        self.tema = tema
        self.bucle = asyncio.new_event_loop()
        self.cliente: ClaudeSDKClient | None = None
        self._listo = threading.Event()
        threading.Thread(target=self._arrancar, daemon=True).start()
        self._listo.wait(timeout=90)

    def _arrancar(self) -> None:
        asyncio.set_event_loop(self.bucle)
        self.bucle.run_until_complete(self._abrir())
        self.bucle.run_forever()

    async def _abrir(self) -> None:
        opciones = colita.construir_opciones(self.tema)
        self.cliente = ClaudeSDKClient(options=opciones)
        await self.cliente.connect()
        self._listo.set()

    async def _preguntar(self, mensaje: str) -> str:
        assert self.cliente is not None
        await self.cliente.query(mensaje)
        partes: list[str] = []
        async for msg in self.cliente.receive_response():
            if isinstance(msg, AssistantMessage):
                for bloque in msg.content:
                    if isinstance(bloque, TextBlock):
                        partes.append(bloque.text)
        return "\n".join(partes).strip() or "(sin respuesta)"

    def preguntar(self, mensaje: str) -> str:
        futuro = asyncio.run_coroutine_threadsafe(self._preguntar(mensaje), self.bucle)
        return futuro.result(timeout=600)

    def interrumpir(self) -> None:
        """Corta la respuesta a medias sin tirar la sesion.

        `interrupt()` es del propio SDK: deja el cliente vivo y la conversacion
        entera en pie, asi que Diego puede corregir y seguir donde estaba en
        vez de empezar de cero.
        """
        if self.cliente is None:
            return
        futuro = asyncio.run_coroutine_threadsafe(self.cliente.interrupt(), self.bucle)
        futuro.result(timeout=15)


def _saludo() -> str:
    """Lo primero que dice al despertar. Varia por hora para no cansar."""
    import datetime as dt
    import random

    h = dt.datetime.now().hour
    momento = "Buenos días" if h < 12 else "Buenas tardes" if h < 20 else "Buenas noches"
    return random.choice([
        f"{momento}, Diego. ¿Qué necesitas?",
        f"{momento}. Dime.",
        f"Aquí estoy. ¿En qué te ayudo?",
        f"{momento}, Diego. Te escucho.",
    ])


import re

# Encabezado de una seccion de fuentes: "## Fuentes", "**Referencias:**",
# "Fuentes consultadas", "Bibliografia"...
_CABECERA_FUENTES = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*)?(?:\*\*|__)?[ \t]*"
    r"(?:fuentes|referencias|bibliograf[ií]a|enlaces|links|sources|citas)"
    r"\b[^\n]*$",
    re.I | re.M,
)
# Sin tragarse la puntuacion final: si `...cosa,` entra en el enlace, al
# quitarlo desaparece tambien la coma y la frase queda coja.
_URL = re.compile(r"(?:https?://|www\.)\S*[^\s.,;:!?)\]}»\"']", re.I)
_CITA_CORCHETE = re.compile(r"\[\s*\d+\s*\]")     # referencias tipo [1], [12]


def _sin_fuentes(texto: str) -> tuple[str, int]:
    """Separa el cuerpo de las fuentes. Devuelve (cuerpo, cuantas fuentes habia).

    Diego lo pidio asi el 2026-08-11: leer veinte URLs en voz alta es
    insoportable y con el tiempo iba a hacerse inmanejable. Las fuentes siguen
    escritas en el chat —ahi no se toca nada—; lo que cambia es que no se
    dictan. Colita solo avisa de que estan y se ofrece a mirar la que le digan.
    """
    cabecera = _CABECERA_FUENTES.search(texto)
    if cabecera:
        cuerpo, cola = texto[: cabecera.start()], texto[cabecera.start():]
    else:
        cuerpo, cola = texto, ""

    urls = set(_URL.findall(cola)) | set(_URL.findall(cuerpo))
    cuantas = len(urls)
    if cola and not cuantas:
        # Una lista de fuentes sin enlaces: cuenta las vinyetas.
        cuantas = len(re.findall(r"^[ \t]*(?:[-*•]|\d+[.)])[ \t]+\S", cola, re.M))

    # Un solo enlace suelto en mitad de una frase no es "una seccion de
    # fuentes": quitarlo basta y la frase sigue sonando natural. El aviso solo
    # tiene sentido cuando de verdad hay una lista que leer seria un castigo.
    if not cola and cuantas < 2:
        cuantas = 0

    return cuerpo, cuantas


def _aviso_fuentes(cuantas: int) -> str:
    if cuantas <= 0:
        return ""
    if cuantas == 1:
        return (" Te dejé una fuente escrita en el chat, ya revisada. "
                "Si quieres que entre en ella, dime.")
    return (f" Te dejé {cuantas} fuentes escritas en el chat, ya revisadas. "
            "Si quieres que entre en alguna en concreto, dime cuál.")


def _para_decir(texto: str, tope: int = 400) -> str:
    """Lo que se dice en voz alta no es lo que se escribe.

    Quita markdown, rutas, bloques de codigo y la lista de fuentes — leerlos en
    voz alta es ruido — y recorta a un parrafo hablado.
    """
    t, cuantas_fuentes = _sin_fuentes(texto)

    t = re.sub(r"```.*?```", " ", t, flags=re.S)               # bloques de codigo
    t = re.sub(r"`[^`]*`", " ", t)                             # codigo en linea
    t = re.sub(r"^\s*[-*#>|]+\s*", "", t, flags=re.M)          # vinyetas y titulos
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)             # enlaces markdown
    t = _CITA_CORCHETE.sub("", t)                              # referencias [1]
    t = _URL.sub("", t)                                        # urls sueltas
    t = re.sub(r"[*_]{1,2}([^*_]+)[*_]{1,2}", r"\1", t)        # negritas
    t = re.sub(r"[A-Za-z]:\\[^\s]+", "esa ruta", t)            # rutas de Windows
    t = re.sub(r"[ \t]*\(\s*\)", "", t)                        # parentesis vacios
    t = re.sub(r"\s+([,.;:])", r"\1", t)                       # espacios colgados
    t = re.sub(r"\s+", " ", t).strip()

    if len(t) > tope:
        corte = t.rfind(".", 0, tope)
        t = t[: corte + 1] if corte > tope // 2 else t[:tope] + "…"

    # El aviso se pega DESPUES de recortar, para que nunca se lo coma el tope.
    return (t + _aviso_fuentes(cuantas_fuentes)).strip()


# ── Acuse de recibo ─────────────────────────────────────────────────────────
#
# Diego lo pidió el 2026-08-12: quedarse mirando un orbe que dice "pensando"
# sin saber si son dos segundos o dos minutos es lo que más desespera. Colita
# contesta al instante diciendo qué va a hacer y si va para largo.
#
# Se decide aquí, con palabras, y no preguntándole al modelo: preguntar
# costaría los mismos segundos que queremos tapar. Es una heurística; se
# equivocará alguna vez, y da igual — el valor está en responder YA.

_LARGAS = (
    "investiga", "investigar", "busca en", "búscame", "buscame", "en la web",
    "en internet", "en github", "repos", "repositorio", "papers", "paper",
    "analiza", "análisis", "analisis", "compara", "comparar", "revisa todo",
    "revisa mis", "lee el", "lee la", "resume el", "resume la", "resumen de",
    # "excel" a secas no: "abre el Excel" es abrir un programa, cosa de un
    # segundo. Lo largo es fabricar uno.
    "entrena", "modelo", "dataset", "un excel", "a excel", "hoja de cálculo",
    "informe", "documento",
    "en mis notas", "en el vault", "en mis documentos", "en mi drive",
    "correos", "calendario", "descarga", "escribe una nota", "guarda en",
)
_CORTAS = (
    "volumen", "sube", "baja", "silencia", "abre", "cierra", "pon ", "pausa",
    "qué hora", "que hora", "hora es", "estado de", "cómo está", "como esta",
    "batería", "bateria", "wifi", "reproduce", "siguiente", "anterior",
)

_FRASES_LARGAS = (
    "Dame un momento, Diego, que esto lo tengo que investigar bien. "
    "Es de las que tardan, pero te aviso en cuanto lo tenga.",
    "Voy a ello. Este es un proceso largo, así que puede demorar un poco; "
    "te aviso apenas termine.",
    "Ahora mismo me pongo. Como hay que buscar y contrastar, va para rato, "
    "pero no te dejo colgado: te aviso.",
    "Entendido. Esto lleva su tiempo porque tengo que revisarlo con calma. "
    "Te voy avisando.",
)
_FRASES_CORTAS = (
    "Va, eso es rápido. Ahora lo hago y te aviso.",
    "Hecho en un segundo, dame nada más.",
    "Eso es cortito. Ya mismo te digo.",
    "Enseguida. Es rápido.",
)
_FRASES_NEUTRAS = (
    "Dame un momento y te digo.",
    "Ahí voy. En cuanto lo tenga, te aviso.",
    "Déjame verlo y te cuento.",
)


def _cuanto_tarda(mensaje: str) -> str:
    """'larga', 'corta' o 'neutra'. Solo mira palabras: tiene que ser instantáneo."""
    m = mensaje.lower()
    if any(p in m for p in _LARGAS):
        return "larga"
    if any(p in m for p in _CORTAS):
        return "corta"
    # Sin señales claras, la longitud de lo que pide orienta bastante bien.
    return "larga" if len(m) > 140 else "neutra"


def _acuse(mensaje: str) -> str:
    import random

    tipo = _cuanto_tarda(mensaje)
    if tipo == "larga":
        return random.choice(_FRASES_LARGAS)
    if tipo == "corta":
        return random.choice(_FRASES_CORTAS)
    return random.choice(_FRASES_NEUTRAS)


class Api:
    """Puente entre el HTML y el cerebro."""

    def __init__(self) -> None:
        self._cerebro: Cerebro | None = None
        self._ventana: webview.Window | None = None

    def avisar(self, mensaje: str) -> str:
        """Contesta al instante: qué va a hacer y si va para largo.

        Se llama ANTES de `preguntar`, para que Diego no se quede mirando un
        «pensando» mudo sin saber si son dos segundos o dos minutos. Devuelve
        la frase para escribirla también en el panel.
        """
        frase = _acuse(mensaje)
        voz.hablar(frase, bloquear=False)
        # Cuando terminara de decirlo. La respuesta espera su turno (una sola
        # voz a la vez), asi que el orbe tiene que contar tambien esta espera.
        self._fin_aviso = time.time() + max(1.2, len(frase) / 14.0)
        log(f"aviso: {frase!r}", "orbe")
        return frase

    def preguntar(self, mensaje: str) -> str:
        if self._cerebro is None:
            self._cerebro = Cerebro()
        self._ultimo_mio = mensaje     # por si Diego para y quiere reescribirlo
        try:
            respuesta = self._cerebro.preguntar(mensaje)
        except Exception as e:  # que un fallo no se coma la ventana
            fallo("el cerebro no respondio", "cerebro")
            return f"Se me cruzaron los cables: {e}"
        # Hablar sin bloquear: el texto aparece ya y la voz va detras.
        dicho = _para_decir(respuesta)
        voz.hablar(dicho, bloquear=False)
        # Cuanto va a durar hablando, para que el orbe no vuelva a reposo antes
        # de que Colita termine la frase. Kokoro a velocidad 1.15 dice unos
        # 14 caracteres por segundo; medido con las pruebas de voz.py.
        espera = max(0.0, getattr(self, "_fin_aviso", 0.0) - time.time())
        self._segundos_voz = espera + max(1.2, len(dicho) / 14.0)
        return respuesta

    def duracion_voz(self) -> float:
        """Segundos que va a tardar en decir la ultima respuesta."""
        return float(getattr(self, "_segundos_voz", 1.6))

    def escuchar(self, seguimiento: bool = False) -> str:
        """Graba del microfono y devuelve lo transcrito.

        `seguimiento` = es el turno siguiente de una conversacion ya empezada.
        Ahi no se puede esperar 25 s a que Diego hable: si en 6 s no dice nada,
        la conversacion se da por terminada.
        """
        self.silenciar_despertador(True)   # que no se oiga a si misma
        try:
            texto, tiempos = voz.escuchar(espera_inicial=6.0 if seguimiento else None)
            log(f"{tiempos} -> {texto!r}", "oido")
            return texto
        except Exception as e:
            fallo("el microfono fallo al grabar", "oido")
            return f"__error__ {e}"
        finally:
            self.silenciar_despertador(False)

    def conversacion(self, activa: bool) -> None:
        """Mientras dura una conversacion, la palabra de activacion se apaga.

        Era el segundo bug que vio Diego: al responderle por voz, el despertador
        oia su respuesta, creia que lo estaban llamando otra vez y saludaba de
        nuevo por encima de la conversacion. Dentro de una conversacion ya no
        hace falta llamarla: ya está escuchando.
        """
        activa = bool(activa)
        if activa == getattr(self, "_conversando", False):
            return
        self._conversando = activa
        self.silenciar_despertador(activa)
        log("conversación abierta" if activa else "conversación cerrada", "orbe")

    # ---------------------------------------------------------------- clima
    # Se pide desde Python y no desde la ventana: asi no depende de CORS ni de
    # que la pagina tenga permiso de red, y se puede cachear de verdad.
    # wttr.in no pide clave ni registro, que es justo lo que hace falta aqui.

    def clima(self) -> dict:
        cache = getattr(self, "_clima", None)
        if cache and time.time() - cache["cuando"] < 900:   # 15 minutos
            return cache["datos"]

        datos = {"temp": "—", "desc": "", "ok": False}
        try:
            import urllib.request

            url = "https://wttr.in/Lima?format=%t|%C&lang=es"
            pet = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
            with urllib.request.urlopen(pet, timeout=6) as r:
                crudo = r.read().decode("utf-8", "replace").strip()
            temp, _, desc = crudo.partition("|")
            datos = {
                "temp": temp.replace("+", "").strip(),
                "desc": desc.strip().lower(),
                "ok": True,
            }
        except Exception:
            fallo("no pude leer el clima", "clima")

        self._clima = {"cuando": time.time(), "datos": datos}
        return datos

    def metricas(self) -> dict:
        """Alimenta los medidores del panel."""
        import psutil

        vault = Path(r"C:\Users\diego\Documents\Obsidian Vault\Claude Diego")
        notas, hoy = 0, 0
        try:
            corte = time.time() - 86400
            for p in vault.rglob("*.md"):
                notas += 1
                if p.stat().st_mtime > corte:
                    hoy += 1
        except Exception:
            pass

        # Bateria: en un portatil es de lo poco que se mira a diario.
        bat = None
        try:
            b = psutil.sensors_battery()
            if b is not None:
                bat = {"pct": round(b.percent), "enchufada": bool(b.power_plugged)}
        except Exception:
            pass

        d = psutil.disk_usage("C:\\")
        return {
            "cpu": round(psutil.cpu_percent(interval=0.15)),
            "ram": round(psutil.virtual_memory().percent),
            "disco": round(d.percent),
            "notas": notas,
            "notas_hoy": hoy,
            "bateria": bat,
            "tema": getattr(self._cerebro, "tema", "general"),
        }

    # ------------------------------------------------------- foco de estudio
    # Un temporizador que AVISA HABLANDO es distinto de uno que parpadea: no
    # hay que estar mirando la pantalla para enterarse, que es justo el punto
    # de estudiar concentrado.

    def iniciar_foco(self, minutos: int, asunto: str = "") -> str:
        try:
            minutos = max(1, min(180, int(minutos)))
        except Exception:
            minutos = 25
        asunto = (asunto or "").strip()

        anterior = getattr(self, "_foco", None)
        if anterior is not None and anterior.is_alive():
            self._parar_foco.set()

        self._parar_foco = threading.Event()
        self._fin_foco = time.time() + minutos * 60
        self._asunto_foco = asunto
        parar = self._parar_foco

        def contar() -> None:
            if parar.wait(minutos * 60):
                return                      # lo cancelaron
            de_que = f" de {asunto}" if asunto else ""
            voz.hablar(
                f"Se acabaron los {minutos} minutos{de_que}. "
                "Levántate un momento y me dices si seguimos.",
                bloquear=False,
            )
            log(f"foco terminado: {minutos} min {asunto!r}", "foco")

        self._foco = threading.Thread(target=contar, daemon=True)
        self._foco.start()
        log(f"foco iniciado: {minutos} min {asunto!r}", "foco")
        return f"{minutos} minutos{' de ' + asunto if asunto else ''}"

    def estado_foco(self) -> dict:
        fin = getattr(self, "_fin_foco", 0.0)
        quedan = fin - time.time()
        hilo = getattr(self, "_foco", None)
        if quedan <= 0 or hilo is None or not hilo.is_alive():
            return {"activo": False}
        return {
            "activo": True,
            "segundos": int(quedan),
            "asunto": getattr(self, "_asunto_foco", ""),
        }

    def cancelar_foco(self) -> None:
        p = getattr(self, "_parar_foco", None)
        if p is not None:
            p.set()
        self._fin_foco = 0.0
        log("foco cancelado", "foco")

    def elegir_archivo(self) -> str:
        """Abre el selector de Windows y devuelve la ruta elegida."""
        if not self._ventana:
            return ""
        try:
            elegidos = self._ventana.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=(
                    "Datos y documentos (*.csv;*.xlsx;*.xls;*.json;*.parquet;"
                    "*.pdf;*.docx;*.txt;*.md;*.ipynb;*.py)",
                    "Todos los archivos (*.*)",
                ),
            )
        except Exception as e:
            return f"__error__ {e}"
        return elegidos[0] if elegidos else ""

    def copiar(self, texto: str) -> None:
        if self._ventana:
            self._ventana.evaluate_js(
                "navigator.clipboard.writeText(" + repr(texto).replace("'", '"', 1) + ")"
            )

    def redimensionar(self, abierto: bool) -> None:
        if self._ventana:
            w, h = GRANDE if abierto else CHICO
            if abierto and getattr(self, "_enorme", False):
                w, h = ENORME
            self._ventana.resize(w, h)

    def agrandar(self, si: bool) -> None:
        """Alterna entre el panel normal y uno mas ancho para leer a gusto."""
        self._enorme = bool(si)
        if self._ventana:
            w, h = ENORME if si else GRANDE
            self._ventana.resize(w, h)
        log(f"panel {'agrandado' if si else 'normal'}", "orbe")

    def minimizar(self) -> None:
        """Se quita de en medio sin cerrarse: sigue oyendo «Colita, actívate»."""
        if not self._ventana:
            return
        try:
            self._ventana.minimize()
        except Exception:
            # Ventana sin marco: si el gestor no la sabe minimizar, se esconde.
            # Vuelve con la palabra de activacion o con Ctrl+Alt+C.
            fallo("no pude minimizar; la escondo", "orbe")
            self._ventana.hide()
        log("minimizada (sigue escuchando)", "orbe")

    def parar(self) -> str:
        """Para todo lo que este haciendo y devuelve lo ultimo que dijo Diego.

        Tres cosas a la vez, porque «para» significa las tres: callar la voz,
        tirar la grabacion en curso e interrumpir al cerebro. La conversacion
        NO se pierde — solo se corta este turno — y el texto vuelve a la caja
        para poder corregirlo y mandarlo otra vez.
        """
        log("parada manual", "orbe")
        voz.callar()
        try:
            if self._cerebro is not None:
                self._cerebro.interrumpir()
        except Exception:
            fallo("no pude interrumpir al cerebro", "orbe")
        return getattr(self, "_ultimo_mio", "")

    # --------------------------------------------------------------- bandeja
    # Diego tenía razón: si la ventana está escondida y no hay nada en la barra
    # de tareas, Colita "no existe" y no hay forma de llamarla salvo la palabra
    # o el atajo. La bandeja del reloj la deja siempre a un clic, sin ocupar
    # sitio y sin salir en Alt+Tab.

    def iniciar_bandeja(self) -> None:
        try:
            import pystray
            from PIL import Image
        except Exception:
            fallo("sin pystray: no habrá icono en la bandeja", "bandeja")
            return

        icono_png = AQUI / "colita.png"
        try:
            imagen = Image.open(icono_png)
        except Exception:
            fallo(f"no encuentro {icono_png}; genera el icono con hacer_icono.py", "bandeja")
            return

        def mostrar(*_):
            self.activar_por_atajo()

        def esconder(*_):
            if self._ventana:
                self._ventana.hide()

        def parar(*_):
            self.parar()

        def cerrar(*_):
            self.salir(descansar=True)

        menu = pystray.Menu(
            pystray.MenuItem("Abrir Colita", mostrar, default=True),
            pystray.MenuItem("Callar / parar", parar),
            pystray.MenuItem("Esconder", esconder),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Cerrar Colita", cerrar),
        )
        self._bandeja = pystray.Icon(
            "colita", imagen, "Colita — di «Colita, actívate» o Ctrl+Alt+C", menu
        )
        threading.Thread(target=self._bandeja.run, daemon=True).start()
        log("icono en la bandeja listo", "bandeja")

    def detener_bandeja(self) -> None:
        b = getattr(self, "_bandeja", None)
        if b is not None:
            try:
                b.stop()
            except Exception:
                pass

    def esconder(self) -> str:
        """La ✕ esconde, no mata. Colita sigue oyendo y queda en la bandeja.

        Antes preguntaba «¿la cierro del todo?» cada vez, y era molesto y
        equivocado: cerrar de verdad un asistente que tiene que oírte no es lo
        que quiere nadie al pulsar una ✕. Ahora se va a la bandeja del reloj,
        que es donde vive este tipo de programa. Para cerrarla del todo está
        «cerrar colita» en la barra del panel o en el menú de la bandeja.
        """
        if self._ventana:
            self._ventana.hide()
        log("escondida en la bandeja; sigue escuchando", "orbe")
        return "ok"

    def salir_preguntando(self) -> bool:
        """Cierra, pero preguntando con un dialogo del sistema.

        No con `confirm()` de JavaScript: WebView2 puede tragarselo sin
        mostrarlo, y entonces el boton no hace nada. El dialogo nativo es el
        mismo que ya se usa para pedir permiso de herramientas.
        """
        if not self._ventana:
            return False
        seguro = bool(self._ventana.create_confirmation_dialog(
            "Cerrar a Colita",
            "¿La cierro del todo?\n\n"
            "Deja de escucharte y se quita de la bandeja del reloj. Vuelve con "
            "el acceso directo de Colita, o sola al reiniciar la laptop.\n\n"
            "Si solo quieres quitarla de en medio, la ✕ la esconde y sigue "
            "oyéndote. Si quieres que se calle, el botón ■ de parar.",
        ))
        if seguro:
            self.salir(descansar=True)
        return seguro

    def salir(self, descansar: bool = False) -> None:
        """`descansar` = cerrada a proposito; el vigilante no debe revivirla.

        Sin esto, cerrarla con la ✕ duraba como mucho diez minutos: la tarea
        programada la volvia a levantar y parecia que el boton no servia.
        """
        log("cerrando por peticion de Diego", "orbe")
        if descansar:
            try:
                DESCANSO.write_text("cerrada a proposito por Diego\n", encoding="utf-8")
                log("marcada como descansando; el vigilante la dejara en paz", "orbe")
            except Exception:
                fallo("no pude escribir la marca de descanso", "orbe")
        voz.callar()
        self.detener_atajo()
        self.detener_despertador()
        self.detener_bandeja()
        if self._ventana:
            self._ventana.destroy()

    # ---------------------------------------------------------------- atajo
    # Idea tomada de Gzsun4/jarvis-ai-mod: un atajo global es mas fiable que
    # la palabra de activacion y no obliga a tener el microfono siempre abierto.
    # Ctrl+Alt+C  ->  "Colita, activate"

    def activar_por_atajo(self) -> None:
        if not self._ventana:
            return
        self._ventana.show()
        self._ventana.evaluate_js(
            "(function(){"
            " if(!document.body.classList.contains('abierto')){"
            "   document.getElementById('orbe').click();"
            " }"
            " document.getElementById('texto').focus();"
            "})()"
        )

    def iniciar_atajo(self) -> None:
        self._atajo = keyboard.GlobalHotKeys(
            {"<ctrl>+<alt>+c": self.activar_por_atajo}
        )
        self._atajo.daemon = True
        self._atajo.start()

    def detener_atajo(self) -> None:
        atajo = getattr(self, "_atajo", None)
        if atajo:
            atajo.stop()

    # ---------------------------------------------------------- despertador
    def iniciar_despertador(self) -> None:
        """"Colita, activate" -> abre el panel y se pone a escuchar."""
        def despertar():
            """Aparece, saluda en voz alta y se pone a escuchar.

            Cada paso queda registrado por separado: si alguno se cuelga —y
            `evaluate_js` desde un hilo que no es el de la ventana puede
            hacerlo— el registro dice exactamente cual, en vez de dejarnos
            adivinando como hasta ahora.
            """
            if not self._ventana:
                log("me llamaron pero la ventana no existe todavia", "despertador")
                return
            log("mostrando la ventana", "despertador")
            self._ventana.show()
            try:
                self._ventana.on_top = True     # por encima de todo lo demas
            except Exception:
                pass

            # NO se abre el panel de conversación. Si Diego la llamó hablando,
            # es que quiere hablar, no leer: que aparezca de golpe una ventana
            # grande con el chat es justo lo que él no quería. Se queda en la
            # bolita, que es su foco. El panel se abre si él hace clic.
            #
            # Primero «activándose», y solo después el saludo: ver que le oyó
            # ANTES de que empiece a sonar es lo que quita la sensación de que
            # no funciona.
            self._ventana.evaluate_js("window.colita && window.colita.activando()")

            frase = _saludo()
            log(f"saludando: {frase!r}", "despertador")
            self._ventana.evaluate_js(
                "window.colita && window.colita.saludo(%s)" % json.dumps(frase)
            )
            voz.hablar(frase, bloquear=True)

            # Y a partir de aquí, conversación seguida: ella escucha, responde
            # y vuelve a escuchar sin que haya que llamarla otra vez.
            log("conversación abierta, te escucho", "despertador")
            self._ventana.evaluate_js("window.colita && window.colita.conversar()")

        def oido(texto: str) -> None:
            log(f"oigo: {texto!r}", "despertador")

        self._despertador = despertador.Despertador(
            al_despertar=despertar, al_oir=oido
        )
        self._despertador.start()

    def detener_despertador(self) -> None:
        d = getattr(self, "_despertador", None)
        if d:
            d.detener()

    def silenciar_despertador(self, silencio: bool) -> None:
        """Se apaga mientras Colita graba, para no oirse a si misma."""
        d = getattr(self, "_despertador", None)
        if d:
            d.silenciar(silencio)


_mutex = None


def _poner_icono_en_la_ventana() -> None:
    """Cuelga el .ico de la ventana de Colita.

    `webview.start(icon=...)` no siempre llega a la barra de tareas: ahi manda
    el icono asociado al HWND. Se busca la ventana por su titulo y se le manda
    WM_SETICON con el icono grande y el chico. Se reintenta porque la ventana
    tarda un poco en existir.
    """
    if os.name != "nt":
        return
    import ctypes

    ico = AQUI / "colita.ico"
    if not ico.exists():
        log("no hay colita.ico; genera el icono con hacer_icono.py", "icono")
        return

    u32 = ctypes.windll.user32
    IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x10, 0x40
    WM_SETICON, ICON_SMALL, ICON_BIG = 0x0080, 0, 1

    for _ in range(40):                      # hasta 20 s
        hwnd = u32.FindWindowW(None, "Colita")
        if hwnd:
            try:
                for tam, cual in ((16, ICON_SMALL), (32, ICON_BIG)):
                    h = u32.LoadImageW(None, str(ico), IMAGE_ICON, tam, tam,
                                       LR_LOADFROMFILE | LR_DEFAULTSIZE)
                    if h:
                        u32.SendMessageW(hwnd, WM_SETICON, cual, h)
                log("icono puesto en la ventana", "icono")
            except Exception:
                fallo("no pude poner el icono en la ventana", "icono")
            return
        time.sleep(0.5)
    log("no encontré la ventana para ponerle el icono", "icono")


def _soy_la_unica() -> bool:
    """False si ya hay otra Colita corriendo.

    Hace falta porque ahora la arrancan tres cosas: el acceso directo de Inicio,
    la tarea programada que la revive, y el propio Diego con `Colita.bat`. Sin
    esto acabarian dos o tres escuchando el mismo microfono y hablando encima.

    El mutex se guarda en un global a proposito: si se recolecta, Windows lo
    libera y el candado desaparece.
    """
    global _mutex
    if os.name != "nt":
        return True
    import ctypes

    k32 = ctypes.windll.kernel32
    _mutex = k32.CreateMutexW(None, False, "ColitaOrbeInstanciaUnica")
    ERROR_YA_EXISTE = 183
    return k32.GetLastError() != ERROR_YA_EXISTE


def main() -> None:
    import sys

    vigilante = "--vigilante" in sys.argv

    arranque("el orbe (vigilante)" if vigilante else "el orbe")

    if vigilante:
        # La tarea programada solo repone a Colita si se cayo sola. Si Diego la
        # cerro con la ✕, se queda cerrada: eso es lo que significa cerrar.
        if DESCANSO.exists():
            log("Diego la cerro a proposito; no la levanto", "vigilante")
            return
    else:
        # Arranque manual o al iniciar sesion: se acabo el descanso.
        try:
            DESCANSO.unlink(missing_ok=True)
        except Exception:
            pass

    if not _soy_la_unica():
        log("ya habia otra Colita despierta; me retiro sin hacer nada")
        return
    api = Api()
    ventana = webview.create_window(
        "Colita",
        str(AQUI / "orbe.html"),
        js_api=api,
        width=CHICO[0],
        height=CHICO[1],
        frameless=True,
        easy_drag=True,
        on_top=True,
        transparent=True,
        resizable=False,
        background_color="#000000",
        hidden=True,   # invisible hasta que la llames: "todo cerrado" de verdad
    )

    # `hidden=True` no basta: pywebview la muestra igual al arrancar. Hay que
    # esconderla otra vez cuando la ventana ya existe.
    def _esconder() -> None:
        import time as _t
        _t.sleep(1.2)
        try:
            ventana.hide()
        except Exception:
            pass

    threading.Thread(target=_esconder, daemon=True).start()
    api._ventana = ventana

    # Sin consola no hay input(): el permiso se pide con un dialogo del sistema.
    def permiso_grafico(herramienta: str, entrada: dict) -> bool:
        resumen = str(entrada)
        if len(resumen) > 260:
            resumen = resumen[:260] + "…"
        return bool(
            ventana.create_confirmation_dialog(
                "Colita pide permiso",
                f"Quiere usar «{herramienta}».\n\n{resumen}\n\n¿La autorizas?",
            )
        )

    colita.pedir_permiso = permiso_grafico
    api.iniciar_atajo()
    api.iniciar_despertador()
    api.iniciar_bandeja()
    threading.Thread(target=_poner_icono_en_la_ventana, daemon=True).start()

    # Calentar la voz y el oído en segundo plano. Sin esto, el primer saludo
    # tardaba casi 16 segundos en empezar a sonar y parecía que no funcionaba.
    def _calentar():
        try:
            log(f"calentando motores: {voz.calentar()}", "voz")
        except Exception:
            fallo("no pude calentar los motores de voz", "voz")

    threading.Thread(target=_calentar, daemon=True).start()
    webview.start(icon=str(AQUI / "colita.ico"))
    api.detener_atajo()
    api.detener_despertador()
    api.detener_bandeja()


if __name__ == "__main__":
    main()
