"""
Genera el icono de Colita: `colita.ico`.

Se dibuja por codigo en vez de guardar un PNG suelto para que el repositorio no
dependa de un binario y para poder retocar el diseno cambiando numeros.

El motivo es el mismo del orbe: una esfera geodesica de aristas finas con un
nucleo encendido. Rojo `#c1121f`, el color de Colita en reposo.

    python hacer_icono.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

AQUI = Path(__file__).parent
FONDO = (10, 10, 12, 255)
ATRAS = (150, 40, 55)       # aristas del fondo: rojo apagado, NO negro
DELANTE = (240, 60, 80)     # aristas de delante: neon
NUCLEO = (255, 210, 215)
ESCALA = 4                  # se dibuja x4 y se reduce: bordes suaves


def _icosaedro() -> tuple[list[tuple[float, float, float]], list[tuple[int, int]]]:
    """Vertices y aristas de un icosaedro centrado en el origen."""
    p = (1 + 5 ** 0.5) / 2
    crudos = []
    for a, b in ((0, 1), (1, 0), (1, 0)):
        pass
    base = [
        (-1, p, 0), (1, p, 0), (-1, -p, 0), (1, -p, 0),
        (0, -1, p), (0, 1, p), (0, -1, -p), (0, 1, -p),
        (p, 0, -1), (p, 0, 1), (-p, 0, -1), (-p, 0, 1),
    ]
    n = math.sqrt(1 + p * p)
    vertices = [(x / n, y / n, z / n) for x, y, z in base]

    # Dos vertices son adyacentes si estan a la distancia minima.
    aristas: list[tuple[int, int]] = []
    dmin = None
    for i in range(len(vertices)):
        for j in range(i + 1, len(vertices)):
            d = math.dist(vertices[i], vertices[j])
            dmin = d if dmin is None else min(dmin, d)
    for i in range(len(vertices)):
        for j in range(i + 1, len(vertices)):
            if abs(math.dist(vertices[i], vertices[j]) - dmin) < 1e-6:
                aristas.append((i, j))
    return vertices, aristas


def dibujar(lado: int = 256) -> Image.Image:
    img = Image.new("RGBA", (lado, lado), FONDO)
    d = ImageDraw.Draw(img, "RGBA")

    vertices, aristas = _icosaedro()
    # Giro para que no se vea de frente y se note el volumen.
    ax, ay = 0.5, 0.7
    puestos = []
    for x, y, z in vertices:
        y, z = y * math.cos(ax) - z * math.sin(ax), y * math.sin(ax) + z * math.cos(ax)
        x, z = x * math.cos(ay) + z * math.sin(ay), -x * math.sin(ay) + z * math.cos(ay)
        puestos.append((x, y, z))

    c, r = lado / 2, lado * 0.40

    def plano(v):
        x, y, z = v
        return c + x * r, c + y * r

    # Nada de halo de fondo: catorce elipses translúcidas apiladas se suman y
    # acaban blanqueando el icono entero. El brillo va solo en el núcleo.

    # Las aristas de atras, apagadas pero ROJAS —no negras, que era el fallo—;
    # las de delante, encendidas. Ordenar por profundidad es lo que da
    # sensacion de esfera y no de maranya.
    orden = sorted(aristas, key=lambda e: (puestos[e[0]][2] + puestos[e[1]][2]) / 2)
    for i, j in orden:
        z = (puestos[i][2] + puestos[j][2]) / 2
        t = (z + 1) / 2                       # 0 detras, 1 delante
        color = tuple(int(a + (b - a) * t) for a, b in zip(ATRAS, DELANTE))
        alfa = int(120 + 135 * t)
        grosor = max(1, int(lado * (0.006 + 0.006 * t)))
        d.line([plano(puestos[i]), plano(puestos[j])],
               fill=color + (alfa,), width=grosor)

    # Nucleo: del halo difuso al blanco caliente.
    for radio, color, alfa in (
        (lado * 0.150, (230, 60, 80), 55),
        (lado * 0.105, (245, 110, 130), 110),
        (lado * 0.070, (255, 170, 185), 200),
        (lado * 0.040, NUCLEO, 255),
    ):
        d.ellipse([c - radio, c - radio, c + radio, c + radio], fill=color + (alfa,))
    return img


def main() -> None:
    # Supermuestreo: se dibuja grande y se reduce, que es lo que da los bordes
    # suaves. PIL no tiene antialias en `line`.
    grande = dibujar(256 * ESCALA).resize((256, 256), Image.LANCZOS)
    destino = AQUI / "colita.ico"
    # Todos los tamanos que pide Windows: barra de tareas, bandeja y escritorio.
    grande.save(destino, format="ICO",
                sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40),
                       (48, 48), (64, 64), (128, 128), (256, 256)])
    grande.save(AQUI / "colita.png")
    print(f"escrito {destino}")


if __name__ == "__main__":
    main()
