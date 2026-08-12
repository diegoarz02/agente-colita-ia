# Agente Colita IA

Asistente personal de voz que vive en el escritorio de Windows: escucha su nombre,
responde hablando y trabaja sobre los archivos y las notas de su dueño.

No es un envoltorio de un chat. Es un agente residente con memoria propia, una lista de
autoridad implementada como código y voz local en las dos direcciones.

```
        ◉  «Colita, actívate»
        │
        ├── oye        Whisper (faster-whisper), local, CPU
        ├── razona     Claude Agent SDK + servidores MCP
        ├── habla      Kokoro-82M ONNX, local
        └── recuerda   vault de Obsidian indexado con RAG
```

## Qué hace

- **Se activa por voz.** Detecta «Colita, actívate» con el micrófono abierto y un consumo
  en reposo despreciable, sin entrenar un modelo propio ni depender de un servicio
  externo.
- **Habla y escucha en local.** El reconocimiento y la síntesis no salen de la máquina.
  Solo el razonamiento va a la nube.
- **Vive escondida.** Sin ventana, sin consola, arranca con Windows y se revive sola si
  se cae.
- **Tiene poderes propios.** Control de volumen y aplicaciones, ejecución de Python con
  pandas y scikit-learn, generación de Excel y de informes HTML, y escritura en su propia
  base de conocimiento.
- **Pide permiso antes de actuar.** Leer es libre; modificar, enviar o borrar se recomienda
  y se espera la aprobación. La regla no vive en el prompt, vive en el callback
  `can_use_tool` del SDK.

## Arquitectura

| Archivo | Responsabilidad |
|---|---|
| `orbe.py` | La cara: ventana sin marco, siempre encima, y el puente con el navegador |
| `orbe.html` | La interfaz: esfera geodésica animada, panel de conversación, medidores |
| `colita.py` | El cerebro: personalidad, opciones del SDK y la lista de autoridad |
| `despertador.py` | La palabra de activación |
| `voz.py` | Síntesis (Kokoro) y transcripción (Whisper), con cancelación por turnos |
| `poderes.py` | Servidor MCP con las herramientas propias del asistente |
| `registro.py` | Registro a archivo — imprescindible cuando no hay consola |
| `calibrar.py` | Diagnóstico del micrófono y del umbral de activación |

### Tres decisiones que valen la pena

**1. La palabra de activación no usa un modelo entrenado.**
Entrenar con openWakeWord pide cientos de muestras; Porcupine pide cuenta y clave. En vez
de eso: se escucha en trozos de 1,5 s midiendo energía, y solo cuando hay sonido se
transcribe ese trozo con Whisper `tiny`. La comparación es por distancia de edición, no
por igualdad, porque el modelo pequeño oye «calita», «coleta» y «colida». Coste en reposo:
prácticamente cero.

**2. Silenciar es un contador, no un interruptor.**
Dos cosas la callan a la vez —el saludo y la grabación—, y con un booleano la primera en
terminar reactivaba el micrófono mientras la otra seguía: el asistente se oía a sí mismo.
La cancelación funciona igual, por número de turno: cada frase recuerda en qué turno
nació y se calla sola si el turno ya cambió.

**3. Sin consola, el registro va a archivo desde la primera línea.**
Bajo `pythonw.exe` no hay consola: `sys.stdout` es `None` y `print` no escribe en ninguna
parte, sin lanzar error. Un programa así es indepurable hasta que escribe a un archivo.

## Requisitos

- Windows 10 u 11
- Python 3.13
- [Ollama](https://ollama.com) si se quiere el RAG local sobre las notas
- Una suscripción de Claude o una clave de API para el razonamiento

## Instalación

```bash
python -m venv C:\venvs\colita
C:\venvs\colita\Scripts\pip install -r requirements.txt
```

Los modelos de voz no están en el repositorio (338 MB). Descargar en `modelos/`:

- `kokoro-v1.0.onnx` y `voices-v1.0.bin` desde
  [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx/releases)

Whisper se descarga solo la primera vez.

```bash
C:\venvs\colita\Scripts\pythonw.exe orbe.py
```

Para que arranque con Windows, un acceso directo en la carpeta de Inicio apuntando a esa
misma línea. Para que se revive sola si se cae, una tarea programada que la lance cada
diez minutos: el candado de instancia única hace que los lanzamientos de más no tengan
efecto.

## Uso

| Acción | Cómo |
|---|---|
| Despertarla | decir «Colita, actívate» |
| Invocarla desde cualquier aplicación | `Ctrl` + `Alt` + `C` |
| Abrir el panel | clic en el orbe |
| Parar y corregir | botón ■ o `Esc` |
| Cerrarla | ✕ |

## Personalizar

La personalidad no está en el código: se lee de una nota externa al arrancar, de modo que
se puede reescribir sin tocar Python. La ruta se configura en `colita.py`.

La voz se cambia en una línea de `voz.py` (`KOKORO_VOZ`). El umbral del micrófono se
calibra con `python calibrar.py`, que mide la energía real del micrófono en vez de
adivinarla.

## Estado

En uso diario. Lo que funciona: palabra de activación, atajo global, voz en ambas
direcciones, ocho herramientas propias, memoria sobre el vault, arranque con el sistema.

Pendiente: métricas de falsos positivos del despertador, y un latido que detecte si el
hilo de escucha se cuelga sin lanzar excepción.

## Licencia

MIT. Ver [LICENSE](LICENSE).
