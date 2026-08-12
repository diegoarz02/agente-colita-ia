"""
Diagnostico del microfono y del despertador.

Si "Colita, activate" no responde, la causa esta en uno de estos tres sitios.
Este script los revisa por separado en vez de adivinar:

  1. El microfono no capta        -> se ve en el nivel de energia
  2. El umbral esta mal puesto    -> se ve comparando tu voz con el silencio
  3. Whisper no entiende          -> se ve en lo que transcribe

    C:\\venvs\\colita\\Scripts\\python.exe calibrar.py
"""

from __future__ import annotations

import queue
import time

import numpy as np
import sounddevice as sd

import despertador

FRECUENCIA = 16000
VENTANA = 1.5


def barra(energia: float, ancho: int = 34) -> str:
    lleno = min(ancho, int(energia / 0.05 * ancho))
    return "█" * lleno + "·" * (ancho - lleno)


def main() -> None:
    print("=" * 62)
    print("  DIAGNOSTICO DEL OIDO DE COLITA")
    print("=" * 62)

    print(f"\nMicrofono en uso: {sd.query_devices(kind='input')['name']}")
    print(f"Umbral configurado: {despertador.UMBRAL_VOZ}")

    print("\n[1/3] Midiendo el silencio. No hables durante 3 segundos…")
    silencios = []
    with sd.InputStream(samplerate=FRECUENCIA, channels=1, dtype="float32") as s:
        for _ in range(6):
            datos, _ = s.read(int(FRECUENCIA * 0.5))
            silencios.append(float(np.sqrt(np.mean(datos ** 2))))
    ruido = float(np.mean(silencios))
    print(f"      ruido de fondo: {ruido:.4f}  {barra(ruido)}")

    print("\n[2/3] Ahora di «Colita, activate» un par de veces (6 segundos)…")
    picos = []
    with sd.InputStream(samplerate=FRECUENCIA, channels=1, dtype="float32") as s:
        t0 = time.time()
        while time.time() - t0 < 6:
            datos, _ = s.read(int(FRECUENCIA * 0.25))
            e = float(np.sqrt(np.mean(datos ** 2)))
            picos.append(e)
            print(f"\r      {e:.4f}  {barra(e)}", end="", flush=True)
    voz_pico = max(picos) if picos else 0.0
    print(f"\n      pico de tu voz: {voz_pico:.4f}")

    # El umbral debe caer ENTRE el ruido y la voz, nunca por encima de la voz.
    # La formula anterior (max(ruido*3, pico*0.18)) devolvia valores mayores
    # que el propio pico cuando el ambiente era ruidoso: imposible activarse.
    if voz_pico > ruido:
        sugerido = round(ruido + (voz_pico - ruido) * 0.30, 4)
    else:
        sugerido = round(ruido * 1.3, 4)   # el micro no distingue: caso malo
    print("\n" + "-" * 62)
    if voz_pico < despertador.UMBRAL_VOZ:
        print(f"  PROBLEMA: tu voz ({voz_pico:.4f}) no llega al umbral "
              f"({despertador.UMBRAL_VOZ}).")
        print(f"  Por eso no se activa. Pon UMBRAL_VOZ = {sugerido} en despertador.py")
    elif ruido > despertador.UMBRAL_VOZ:
        print(f"  PROBLEMA: el ruido de fondo ({ruido:.4f}) ya supera el umbral.")
        print(f"  Se dispara sola. Pon UMBRAL_VOZ = {sugerido} en despertador.py")
    else:
        print(f"  Niveles bien. Umbral sugerido para afinar: {sugerido}")
    print("-" * 62)

    print("\n[3/3] Escuchando en vivo. Di «Colita, activate».")
    print("      Veras TODO lo que Whisper entiende. Ctrl+C para salir.\n")

    despertador._cargar()
    cola: queue.Queue = queue.Queue()
    bloque = int(FRECUENCIA * VENTANA)

    def cb(indata, frames, tiempo, estado):
        cola.put(indata.copy())

    try:
        with sd.InputStream(samplerate=FRECUENCIA, channels=1, dtype="float32",
                            blocksize=bloque, callback=cb):
            while True:
                try:
                    trozo = cola.get(timeout=0.5)
                except queue.Empty:
                    continue
                audio = trozo.flatten()
                e = float(np.sqrt(np.mean(audio ** 2)))
                if e < despertador.UMBRAL_VOZ:
                    continue
                segs, _ = despertador._cargar().transcribe(
                    audio, language="es", beam_size=1, vad_filter=True
                )
                texto = " ".join(s.text for s in segs).strip()
                if not texto:
                    print(f"  [{e:.4f}] (voz detectada, sin palabras)")
                    continue
                marca = ">>> DESPIERTA <<<" if despertador._es_llamada(texto) else "ignora"
                print(f"  [{e:.4f}] {texto!r}  ->  {marca}")
    except KeyboardInterrupt:
        print("\nListo.")


if __name__ == "__main__":
    main()
