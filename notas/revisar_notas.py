"""Revisa la página de notas del Portal UCSC y avisa por ntfy si cambió.

Privacidad: el repo es público y los registros de GitHub Actions también.
Por eso el script NUNCA imprime el contenido de la página. Solo guarda
huellas (hashes) de cada línea, no las notas en sí.

Variables de entorno (se configuran como "secrets" en GitHub):
  UCSC_RUT        RUT sin puntos ni dígito verificador
  UCSC_PASSWORD   contraseña del portal
  NTFY_TOPIC      nombre del canal de ntfy (inventa uno largo y difícil de adivinar)
  NTFY_DETALLE    opcional: "1" para incluir las líneas nuevas en la notificación
  NOTAS_SELECTOR  opcional: selector CSS para leer solo una parte de la página
"""

import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

PORTAL = "https://portal.ucsc.cl/alumno"
APP_NOTAS = "https://portal.ucsc.cl/alumno#/apps/app/1"
ESTADO = Path(os.environ.get("ESTADO_PATH", "estado/huellas.json"))

# Líneas que cambian solas (fechas, horas, saludos) y no deben dar aviso.
IGNORAR = re.compile(
    r"(\d{1,2}:\d{2})|(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})|hace \d+|aviso publicado",
    re.IGNORECASE,
)


class LoginRechazado(Exception):
    """El portal rechazó el RUT o la contraseña."""


def huella(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def avisar(titulo: str, mensaje: str, prioridad: str = "high") -> None:
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("Falta NTFY_TOPIC: no se envió la notificación.")
        return
    req = urllib.request.Request(
        f"https://ntfy.sh/{topic}",
        data=mensaje.encode("utf-8"),
        headers={
            "Title": titulo.encode("utf-8").decode("latin-1", "ignore"),
            "Priority": prioridad,
            "Tags": "mortar_board",
            "Click": APP_NOTAS,
        },
    )
    urllib.request.urlopen(req, timeout=20)


def iniciar_sesion(page, rut: str, password: str) -> None:
    page.goto(PORTAL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector("#formulario-ingreso", timeout=30000)
    # Cierra el aviso emergente que aparece sobre el formulario.
    page.evaluate("() => { try { $('.modal').modal('hide'); } catch (e) {} }")
    page.fill("#rut", rut)
    page.fill("input[type=password]", password)
    # El formulario toma los valores recién en el evento "change".
    page.dispatch_event("#rut", "change")
    page.dispatch_event("input[type=password]", "change")
    page.evaluate("() => document.getElementById('button-submit').click()")
    try:
        page.wait_for_function(
            "() => !document.querySelector('#formulario-ingreso')", timeout=45000
        )
    except PWTimeout:
        error = page.locator("#alert-resp").inner_text(timeout=2000).strip()
        if error:
            raise LoginRechazado(error)
        raise RuntimeError("El portal no respondió al iniciar sesión.")


def leer_notas(page) -> list[str]:
    page.goto(APP_NOTAS, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except PWTimeout:
        pass
    page.wait_for_timeout(8000)  # la app carga datos después

    selector = os.environ.get("NOTAS_SELECTOR")
    textos = []
    for frame in page.frames:  # la app puede estar dentro de un iframe
        try:
            if selector:
                loc = frame.locator(selector)
                if loc.count():
                    textos.append(loc.first.inner_text(timeout=5000))
            else:
                textos.append(frame.locator("body").inner_text(timeout=5000))
        except Exception:
            continue

    lineas = []
    for t in textos:
        for linea in t.splitlines():
            linea = " ".join(linea.split())
            if linea and not IGNORAR.search(linea):
                lineas.append(linea)
    print(f"Marcos leídos: {len(page.frames)}. Líneas útiles: {len(lineas)}.")
    return lineas


def main() -> int:
    rut = os.environ.get("UCSC_RUT", "").strip()
    password = os.environ.get("UCSC_PASSWORD", "")
    if not rut or not password:
        print("Faltan UCSC_RUT o UCSC_PASSWORD.")
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        page = browser.new_page(locale="es-CL")
        try:
            iniciar_sesion(page, rut, password)
            lineas = leer_notas(page)
        finally:
            browser.close()

    if len(lineas) < 5:
        print("La página de notas vino casi vacía; no se compara para evitar falsos avisos.")
        return 1

    nuevas = {huella(l): l for l in lineas}
    if not ESTADO.exists():
        ESTADO.parent.mkdir(parents=True, exist_ok=True)
        ESTADO.write_text(json.dumps(sorted(nuevas)))
        print("Primera revisión: se guardó el estado inicial.")
        avisar("Monitor de notas activo", "Te avisaré cuando cambie tu página de notas.", "default")
        return 0

    anteriores = set(json.loads(ESTADO.read_text()))
    agregadas = [l for h, l in nuevas.items() if h not in anteriores]
    ESTADO.write_text(json.dumps(sorted(nuevas)))

    if not agregadas:
        print("Sin cambios.")
        return 0

    print(f"Cambios detectados: {len(agregadas)} línea(s) nueva(s).")
    if os.environ.get("NTFY_DETALLE") == "1":
        cuerpo = "\n".join(agregadas[:15])
    else:
        cuerpo = f"Hay {len(agregadas)} cambio(s) en tu página de notas. Toca para abrir el portal."
    avisar("¡Nueva nota en el portal UCSC!", cuerpo)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except LoginRechazado as e:
        # Salida 2: el workflow se desactiva solo para no bloquear la cuenta
        # (el portal bloquea tras 6 intentos fallidos).
        print(f"Login rechazado: {e}")
        salida = os.environ.get("GITHUB_OUTPUT")
        if salida:
            with open(salida, "a") as f:
                f.write("rechazado=1\n")
        try:
            avisar(
                "Monitor de notas detenido",
                f"El portal rechazó el inicio de sesión ({e}). "
                "Revisa UCSC_RUT/UCSC_PASSWORD y vuelve a activar el workflow.",
            )
        except Exception:
            pass
        sys.exit(2)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
