"""
Voz y oido de Colita.

  hablar(texto)   -> lo dice por los altavoces (SAPI, voz Helena es-ES)
  escuchar()      -> graba del microfono y devuelve el texto (faster-whisper, CPU)

Decision de diseno: SAPI en vez de Kokoro. El instalador de claude-tts-mcp no
detecta Python en esta maquina, y Windows ya trae Helena (es-ES, femenina) sin
descargar nada. Kokoro suena mejor; se puede cambiar aqui sin tocar nada mas.
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

# --------------------------------------------------------------------------
# Voz
# --------------------------------------------------------------------------

VOZ_PREFERIDA = "Helena"   # respaldo SAPI: es-ES, femenina
VELOCIDAD = 180            # palabras por minuto

# Kokoro: voz neuronal, mucho menos robotica que SAPI.
MODELOS = Path(__file__).parent / "modelos"
KOKORO_MODELO = MODELOS / "kokoro-v1.0.onnx"
KOKORO_VOCES = MODELOS / "voices-v1.0.bin"
# Voz de Colita. Cambia esta linea y listo.
#   ef_dora  espanol nativo          af_heart / af_nova / af_bella  mas brillantes
#   if_sara  italiana, timbre claro  pf_dora  portuguesa
# Para oirlas todas:  python _voces.py
KOKORO_VOZ = "af_jessica"  # elegida por Diego el 2026-08-10
KOKORO_VEL = 1.15          # 1.0 arrastra; 1.15 suena mas despierta

_kokoro = None
_kokoro_roto = False

# ── Parar, y una sola voz a la vez ──────────────────────────────────────────
#
# Diego pidió el botón de pánico el 2026-08-11: si Colita arranca a responder
# algo que no era, tiene que poder cortarla a media frase.
#
# No es una bandera sino un contador de turnos, y la razón importa: con una
# bandera, lo que ya estaba encolado la borraba al empezar y hablaba igual
# ("parar" no paraba lo siguiente), y si nadie la borraba el micrófono se
# quedaba muerto. Con el contador, cada frase recuerda en qué turno nació y se
# calla sola si el turno ya cambió.
_turno = 0
_cerrojo_turno = threading.Lock()
# Una sola voz a la vez: desde que Colita avisa "dame un momento" y luego
# responde, hay dos frases en vuelo y sin esto sonaban encima.
_cerrojo_voz = threading.Lock()


def turno_actual() -> int:
    with _cerrojo_turno:
        return _turno


def _cancelado(mio: int) -> bool:
    with _cerrojo_turno:
        return mio != _turno


def callar() -> None:
    """Corta en seco la voz y la grabación, y anula lo que estuviera encolado."""
    global _turno
    with _cerrojo_turno:
        _turno += 1
    try:
        sd.stop()
    except Exception:
        pass


def _cargar_kokoro():
    """Devuelve el motor Kokoro, o None si no se puede usar."""
    global _kokoro, _kokoro_roto
    if _kokoro_roto:
        return None
    if _kokoro is None:
        if not (KOKORO_MODELO.exists() and KOKORO_VOCES.exists()):
            _kokoro_roto = True
            return None
        try:
            from kokoro_onnx import Kokoro
            _kokoro = Kokoro(str(KOKORO_MODELO), str(KOKORO_VOCES))
        except Exception as e:
            print(f"[voz] Kokoro no arranco ({e}); uso la voz de Windows.")
            _kokoro_roto = True
            return None
    return _kokoro


def _frases(texto: str, minimo: int = 60) -> list[str]:
    """Parte en frases para empezar a hablar antes de generarlo todo."""
    import re

    trozos = re.split(r"(?<=[.!?…])\s+", texto)
    salida: list[str] = []
    for t in trozos:
        t = t.strip()
        if not t:
            continue
        if salida and len(salida[-1]) < minimo:
            salida[-1] += " " + t     # junta frases muy cortas
        else:
            salida.append(t)
    return salida or [texto]


def _hablar_kokoro(texto: str, mio: int) -> bool:
    """True si Kokoro lo dijo; False si hay que caer al respaldo.

    Genera la primera frase y la reproduce mientras genera la siguiente: asi
    Colita empieza a hablar en ~1 s en vez de esperar al parrafo entero.
    """
    motor = _cargar_kokoro()
    if motor is None:
        return False

    trozos = _frases(texto)
    try:
        pendiente = motor.create(trozos[0], voice=KOKORO_VOZ, speed=KOKORO_VEL, lang="es")
    except Exception as e:
        global _kokoro_roto
        print(f"[voz] Kokoro fallo al hablar ({e}); uso la voz de Windows.")
        _kokoro_roto = True
        return False

    for i in range(len(trozos)):
        if _cancelado(mio):         # Diego pulso «parar»
            break
        muestras, frec = pendiente
        sd.play(muestras, frec)
        siguiente = None
        if i + 1 < len(trozos):
            try:  # se genera mientras suena la anterior
                siguiente = motor.create(
                    trozos[i + 1], voice=KOKORO_VOZ, speed=KOKORO_VEL, lang="es"
                )
            except Exception:
                siguiente = None
        sd.wait()
        if siguiente is None or _cancelado(mio):
            break
        pendiente = siguiente
    return True


def _motor():
    """pyttsx3 no es reutilizable entre hilos: un motor por llamada."""
    import pyttsx3

    m = pyttsx3.init()
    for v in m.getProperty("voices"):
        if VOZ_PREFERIDA.lower() in v.name.lower():
            m.setProperty("voice", v.id)
            break
    m.setProperty("rate", VELOCIDAD)
    return m


def calentar() -> dict:
    """Carga y estrena los motores al arrancar, para que la primera vez no duela.

    Medido el 2026-08-12 en esta máquina: desde que oía su nombre hasta que
    EMPEZABA a sonar el saludo pasaban **15,8 segundos** — 4,2 de cargar Kokoro
    y 11,6 de la primera generación, que arrastra la inicialización de espeak y
    de la sesión ONNX. Diego creía que no hablaba; simplemente no esperaba
    dieciséis segundos.

    Ya caliente, la misma frase tarda 1,2 s. Así que basta con hacer ese primer
    trabajo al arrancar, en segundo plano, en vez de cobrárselo al saludo.
    """
    t = {}
    t0 = time.perf_counter()
    motor = _cargar_kokoro()
    t["kokoro"] = round(time.perf_counter() - t0, 2)

    if motor is not None:
        t0 = time.perf_counter()
        try:
            # Se genera y se TIRA: solo queremos pagar la inicialización.
            motor.create("Hola.", voice=KOKORO_VOZ, speed=KOKORO_VEL, lang="es")
            t["primera_frase"] = round(time.perf_counter() - t0, 2)
        except Exception:
            t["primera_frase"] = None

    t0 = time.perf_counter()
    try:
        _cargar()                    # Whisper `small`, el del oído
        t["whisper"] = round(time.perf_counter() - t0, 2)
    except Exception:
        t["whisper"] = None
    return t


def hablar(texto: str, bloquear: bool = True) -> float:
    """Dice el texto. Devuelve los segundos que tardo."""
    texto = (texto or "").strip()
    if not texto:
        return 0.0

    mio = turno_actual()            # el turno en el que nace esta frase

    def _decir():
        if _cancelado(mio):         # la pararon antes de que le tocara hablar
            return
        with _cerrojo_voz:          # espera su turno; nunca dos voces a la vez
            if _cancelado(mio):
                return
            if _hablar_kokoro(texto, mio):   # voz neuronal
                return
            if _cancelado(mio):
                return
            m = _motor()            # respaldo: SAPI Helena
            m.say(texto)
            m.runAndWait()
            m.stop()

    t0 = time.perf_counter()
    if bloquear:
        _decir()
    else:
        threading.Thread(target=_decir, daemon=True).start()
    return time.perf_counter() - t0


# --------------------------------------------------------------------------
# Oido
# --------------------------------------------------------------------------

MODELO = "small"        # base = mas rapido, small = mas preciso
FRECUENCIA = 16000
SILENCIO = 0.012        # umbral de energia por debajo del cual es silencio
CORTE = 1.4             # segundos de silencio que cierran la grabacion
MAX_SEG = 25            # tope duro por si el micro se queda abierto

_transcriptor = None


def _cargar():
    global _transcriptor
    if _transcriptor is None:
        from faster_whisper import WhisperModel
        # int8 sobre CPU: lo unico viable sin GPU dedicada
        _transcriptor = WhisperModel(MODELO, device="cpu", compute_type="int8")
    return _transcriptor


def grabar(max_seg: int = MAX_SEG, espera_inicial: float | None = None) -> np.ndarray:
    """Graba hasta que Diego se calla (o hasta el tope).

    `espera_inicial`: si pasa ese tiempo y NADIE ha empezado a hablar, se corta
    y devuelve vacío. Hace falta para la conversación continua: tras responder,
    Colita abre el micrófono por si Diego sigue, y si no sigue no puede
    quedarse veinticinco segundos con el micro abierto esperando.
    """
    mio = turno_actual()
    trozos: queue.Queue = queue.Queue()

    def cb(indata, frames, tiempo, estado):
        trozos.put(indata.copy())

    audio: list[np.ndarray] = []
    silencio_desde = None
    hablo = False
    t0 = time.perf_counter()

    with sd.InputStream(samplerate=FRECUENCIA, channels=1, dtype="float32",
                        blocksize=int(FRECUENCIA * 0.1), callback=cb):
        while time.perf_counter() - t0 < max_seg:
            if _cancelado(mio):        # «parar»: se descarta lo grabado
                return np.zeros(0, dtype="float32")
            try:
                bloque = trozos.get(timeout=0.5)
            except queue.Empty:
                continue
            audio.append(bloque)

            energia = float(np.sqrt(np.mean(bloque ** 2)))
            if energia > SILENCIO:
                hablo = True
                silencio_desde = None
            elif hablo:
                silencio_desde = silencio_desde or time.perf_counter()
                if time.perf_counter() - silencio_desde > CORTE:
                    break
            elif espera_inicial is not None and \
                    time.perf_counter() - t0 > espera_inicial:
                return np.zeros(0, dtype="float32")   # nadie dijo nada

    return np.concatenate(audio).flatten() if audio else np.zeros(0, dtype="float32")


def escuchar(espera_inicial: float | None = None) -> tuple[str, dict]:
    """Graba, transcribe y devuelve (texto, tiempos).

    `espera_inicial` se pasa tal cual a `grabar`: en un turno de seguimiento,
    si nadie habla en esos segundos, se corta y se devuelve vacío.
    """
    t0 = time.perf_counter()
    audio = grabar(espera_inicial=espera_inicial)
    t_grabar = time.perf_counter() - t0

    if audio.size < FRECUENCIA * 0.4:      # menos de medio segundo util
        return "", {"grabar": t_grabar, "transcribir": 0.0, "audio_seg": 0.0}

    # `initial_prompt` sesga el modelo hacia el vocabulario de Diego. Sin esto
    # oye "abastección" donde dijiste "obsidian", y "la parte de" donde dijiste
    # "aparte". beam_size=5 cuesta poco mas y equivoca bastante menos.
    t1 = time.perf_counter()
    segmentos, _ = _cargar().transcribe(
        audio,
        language="es",
        beam_size=5,
        vad_filter=True,
        temperature=0.0,
        condition_on_previous_text=False,
        initial_prompt=(
            "Conversación con Colita, asistente de ciencia de datos. "
            "Vocabulario: Obsidian, vault, notas, tesis, ENAPRES, MLP, RBF, "
            "Python, pandas, dataset, modelo, análisis, Excel, correo, "
            "calendario, Drive, Notion, repositorio, machine learning."
        ),
    )
    texto = " ".join(s.text for s in segmentos).strip()
    t_transcribir = time.perf_counter() - t1

    return texto, {
        "grabar": round(t_grabar, 2),
        "transcribir": round(t_transcribir, 2),
        "audio_seg": round(audio.size / FRECUENCIA, 2),
    }


# --------------------------------------------------------------------------
# Medicion
# --------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if "--voz" in sys.argv or len(sys.argv) == 1:
        frase = "Hola Diego, soy Colita. Ya puedo hablar contigo."
        print(f"Diciendo: {frase!r}")
        seg = hablar(frase)
        print(f"  TTS: {seg:.2f} s  ({len(frase)} caracteres)")

    if "--oido" in sys.argv:
        print("\nCargando el modelo de transcripcion...")
        t0 = time.perf_counter()
        _cargar()
        print(f"  carga: {time.perf_counter() - t0:.1f} s (solo la primera vez)")
        print("\nHabla ahora. Se corta sola cuando te calles.")
        texto, t = escuchar()
        print(f"\n  Escuche: {texto!r}")
        print(f"  audio {t['audio_seg']}s | grabar {t['grabar']}s | transcribir {t['transcribir']}s")
