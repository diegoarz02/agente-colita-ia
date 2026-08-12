"""
Palabra de activacion: "Colita, activate".

Como funciona, y por que asi:

Entrenar una palabra propia con openWakeWord pide generar cientos de muestras y
entrenar un modelo; Porcupine lo hace en minutos pero exige cuenta y clave. Hay
un camino intermedio que funciona hoy y no depende de nadie:

  1. Escuchar el microfono en trozos de 1,5 s y medir energia (casi 0 % de CPU).
  2. Cuando hay voz, transcribir SOLO ese trozo con Whisper `tiny` (~0,2 s).
  3. Si el texto se parece a "colita", despertar.

El paso 2 solo corre cuando alguien habla, asi que la CPU en reposo es
despreciable. Y como usa el mismo Whisper que ya esta instalado, no hace falta
descargar ni entrenar nada.

El parecido se mide con distancia de edicion, no con igualdad: Whisper `tiny`
oye "calita", "colita", "collita", "colitas"... y todas valen.
"""

from __future__ import annotations

import queue
import threading
import time

import numpy as np
import sounddevice as sd

from registro import fallo, log

FRECUENCIA = 16000
VENTANA = 1.5          # segundos por trozo analizado
# Calibrado con la sesion en vivo de Diego (2026-08-11). Los datos mandan:
#
#   'Colita activate'  ->  0.0226   detecto
#   'Coleta'           ->  0.0151   detecto
#   'esta colida'      ->  0.0141   detecto
#
# Subir el umbral a 0.021 dejo fuera dos de esas tres. El error de diseno fue
# querer filtrar el ruido con la energia: para eso ya esta `_es_llamada()`, que
# en su prueba ignoro correctamente TODAS las transcripciones de ruido
# ("Pullos vos grajo", "no soy ayer", "Este va de interaccion"...).
#
# Asi que el umbral solo evita gastar CPU en silencio absoluto, y el filtrado
# de verdad lo hace la palabra. Bajo y permisivo.
UMBRAL_VOZ = 0.009
# 1 y no 2: con 2, "cita" entra dentro del margen y "la cita es manana"
# la despertaba. Con 1 siguen valiendo "calita", "cholita" y "colitas".
TOLERANCIA = 1
LARGO_MINIMO = 5       # descarta palabras cortas antes de comparar
ENFRIAMIENTO = 2.5     # segundos de pausa tras despertar, para no dispararse dos veces

# Una sola palabra, no cinco. Las variantes que oye Whisper `tiny` —"calita",
# "cholita", "colitas", "coleta", "colida"— ya caen todas a distancia 1 de
# "colita", asi que listarlas no anyadia nada: lo que hacia era ensanchar la
# red a distancia 2 y colar palabras ajenas. Con "calita" en la lista, "una
# casita bonita" la despertaba (casita->calita es 1). Probado el 2026-08-12.
DESPERTADORES = ("colita",)

_modelo = None


def _cargar():
    global _modelo
    if _modelo is None:
        from faster_whisper import WhisperModel
        # `tiny` porque solo tiene que reconocer una palabra, no transcribir bien
        try:
            _modelo = WhisperModel("tiny", device="cpu", compute_type="int8")
        except Exception:
            # Sin red (o con Hugging Face caido) la descarga falla aunque el
            # modelo ya este bajado. La cache local basta: 0,8 s. Probado el
            # 2026-08-11 — sin esto, un corte de internet deja a Colita sorda.
            fallo("no pude cargar 'tiny' con red; reintento solo con la cache", "despertador")
            _modelo = WhisperModel(
                "tiny", device="cpu", compute_type="int8", local_files_only=True
            )
    return _modelo


def _distancia(a: str, b: str) -> int:
    """Levenshtein, en corto."""
    if len(a) < len(b):
        a, b = b, a
    previa = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(min(previa[j] + 1, actual[j - 1] + 1, previa[j - 1] + (ca != cb)))
        previa = actual
    return previa[-1]


def _es_llamada(texto: str) -> bool:
    limpio = "".join(c for c in texto.lower() if c.isalpha() or c.isspace())
    for palabra in limpio.split():
        if len(palabra) < LARGO_MINIMO:
            continue
        for clave in DESPERTADORES:
            if _distancia(palabra, clave) <= TOLERANCIA:
                return True
    return False


class Despertador(threading.Thread):
    """Escucha en segundo plano y llama a `al_despertar()` cuando oye su nombre."""

    def __init__(self, al_despertar, al_oir=None):
        super().__init__(daemon=True)
        self.al_despertar = al_despertar
        self.al_oir = al_oir          # opcional: para depurar lo que entiende
        self._parar = threading.Event()
        self._ultimo = 0.0            # cuando desperto por ultima vez
        self._silencios = 0           # cuantos motivos hay ahora para callar
        self._cerrojo = threading.Lock()

    # `activo` es un contador, no un interruptor. Dos cosas la silencian a la
    # vez —el saludo al despertar y la grabacion del microfono— y con un
    # booleano la primera en terminar la reactivaba mientras la otra seguia,
    # asi que Colita se oia a si misma.
    @property
    def activo(self) -> bool:
        return self._silencios == 0

    def silenciar(self, si: bool) -> None:
        with self._cerrojo:
            self._silencios = self._silencios + 1 if si else max(0, self._silencios - 1)

    def detener(self) -> None:
        self._parar.set()

    def run(self) -> None:
        """Nunca muere en silencio.

        Antes, cualquier excepcion aqui —el micro que cambia, un fallo de
        Whisper, un `print` que revienta— mataba el hilo sin dejar rastro:
        bajo `pythonw` no hay consola donde ver la traza. Colita se quedaba
        sorda y no habia forma de saberlo. Ahora todo va al registro y el
        bucle vuelve a abrir el microfono en vez de rendirse.
        """
        while not self._parar.is_set():
            try:
                self._escuchar_sin_parar()
            except Exception:
                fallo("el bucle de escucha se cayo; reabro el microfono en 3 s",
                      "despertador")
                if self._parar.wait(3.0):
                    break
        log("me detengo", "despertador")

    def _escuchar_sin_parar(self) -> None:
        _cargar()
        cola: queue.Queue = queue.Queue()

        def cb(indata, frames, tiempo, estado):
            cola.put(indata.copy())

        bloque = int(FRECUENCIA * VENTANA)
        with sd.InputStream(samplerate=FRECUENCIA, channels=1, dtype="float32",
                            blocksize=bloque, callback=cb):
            log(f"microfono abierto (umbral {UMBRAL_VOZ}); di «Colita, activate»",
                "despertador")
            while not self._parar.is_set():
                try:
                    trozo = cola.get(timeout=0.5)
                except queue.Empty:
                    continue
                if not self.activo or time.time() - self._ultimo < ENFRIAMIENTO:
                    continue

                audio = trozo.flatten()
                if float(np.sqrt(np.mean(audio ** 2))) < UMBRAL_VOZ:
                    continue          # silencio: ni transcribimos

                try:
                    segs, _ = _cargar().transcribe(
                        audio, language="es", beam_size=1, vad_filter=True
                    )
                    texto = " ".join(s.text for s in segs).strip()
                except Exception:
                    fallo("Whisper fallo al transcribir un trozo", "despertador")
                    continue

                if not texto:
                    continue
                if self.al_oir:
                    try:
                        self.al_oir(texto)
                    except Exception:
                        # Un fallo del depurador no puede dejarla sorda.
                        fallo("al_oir reviento", "despertador")
                if _es_llamada(texto):
                    log(f"DESPIERTA con {texto!r}", "despertador")
                    self._despertar_aparte(cola)

    def _despertar_aparte(self, cola: queue.Queue) -> None:
        """Despierta en su propio hilo, no en el de escucha.

        Antes `al_despertar()` se llamaba aqui mismo y bloqueaba el bucle todo
        lo que durase el saludo. En ese hueco la cola acumulaba audio viejo —el
        de la propia Colita hablando— y al volver lo transcribia como si fuese
        Diego. Ahora el bucle sigue vivo, el microfono se silencia mientras
        habla, y al terminar se tira lo que se acumulo.
        """
        self.silenciar(True)

        def tarea() -> None:
            try:
                self.al_despertar()
            except Exception:
                fallo("al_despertar reviento", "despertador")
            finally:
                while True:              # fuera el audio de su propia voz
                    try:
                        cola.get_nowait()
                    except queue.Empty:
                        break
                # El enfriamiento cuenta desde que TERMINA de hablar, no desde
                # que empieza: si no, ya habia expirado al volver y se
                # despertaba a si misma.
                self._ultimo = time.time()
                self.silenciar(False)

        threading.Thread(target=tarea, daemon=True).start()


if __name__ == "__main__":
    print("Cargando el modelo…")
    t0 = time.perf_counter()
    _cargar()
    print(f"listo en {time.perf_counter() - t0:.1f} s\n")
    print('Di "Colita, activate". Ctrl+C para salir.\n')

    d = Despertador(
        al_despertar=lambda: print("  >>> DESPIERTA <<<"),
        al_oir=lambda t: print(f"  oido: {t!r}"),
    )
    d.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        d.detener()
        print("\nAdios.")
