"""Avisa por ntfy cuando un ramo del Portal UCSC muestra "nota nueva".

En la "Ficha del curso", el portal agrega junto al ramo el texto
"(una nota nueva en los últimos 7 días)". Este script solo busca ese
aviso y notifica cuando aparece en un ramo que antes no lo tenía
(o cuando cambia, por ejemplo de "una" a "dos notas nuevas").

Privacidad: el repo es público y los registros de GitHub Actions también.
El script nunca imprime nombres de ramos ni notas en los registros.

Variables de entorno (se configuran como "secrets" en GitHub):
  UCSC_RUT        RUT sin puntos ni dígito verificador
  UCSC_PASSWORD   contraseña del portal
  NTFY_TOPIC      nombre del canal de ntfy (inventa uno largo y difícil de adivinar)
  NTFY_TOKEN      opcional: token de una cuenta gratis de ntfy.sh (evita límites)
Si ntfy falla, se usa de respaldo un issue en el repo (GITHUB_TOKEN).
"""

import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

PORTAL = "https://portal.ucsc.cl/alumno"
APP_NOTAS = "https://portal.ucsc.cl/alumno#/apps/app/1"
ESTADO = Path(os.environ.get("ESTADO_PATH", "estado/avisos.json"))
FALLOS_PARA_AVISAR = 12  # ~1 hora sin poder leer el portal
INTENTOS = 3

# "(una nota nueva en los últimos 7 días)", "(2 notas nuevas ...)", etc.
NOTA_NUEVA = re.compile(r"notas?\s+nuevas?", re.IGNORECASE)


class LoginRechazado(Exception):
    """El portal rechazó el RUT o la contraseña."""


def huella(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _ntfy(titulo: str, mensaje: str, prioridad: int) -> bool:
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return False
    datos = {
        "topic": topic,
        "title": titulo,
        "message": mensaje,
        "priority": prioridad,
        "tags": ["mortar_board"],
        "click": APP_NOTAS,
    }
    headers = {"Content-Type": "application/json"}
    if os.environ.get("NTFY_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['NTFY_TOKEN']}"
    for espera in (0, 5, 20):
        time.sleep(espera)
        try:
            req = urllib.request.Request(
                "https://ntfy.sh/", data=json.dumps(datos).encode("utf-8"), headers=headers
            )
            urllib.request.urlopen(req, timeout=20)
            return True
        except Exception as e:
            print(f"ntfy falló: {getattr(e, 'code', type(e).__name__)}")
    return False


def _issue_github(titulo: str) -> bool:
    """Respaldo: abre un issue; la app de GitHub te manda un push.

    El repo es público, así que el issue no dice ramo ni nota.
    """
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return False
    datos = {"title": titulo, "body": f"Revisa el portal: {APP_NOTAS}"}
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/issues",
            data=json.dumps(datos).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
        )
        urllib.request.urlopen(req, timeout=20)
        return True
    except Exception as e:
        print(f"Issue de respaldo falló: {getattr(e, 'code', type(e).__name__)}")
        return False


def avisar(titulo: str, mensaje: str, prioridad: int = 4, titulo_publico: str = "") -> bool:
    """Envía por ntfy; si falla, usa GitHub. Devuelve True si algo llegó."""
    if _ntfy(titulo, mensaje, prioridad):
        return True
    return _issue_github(titulo_publico or "Aviso del monitor de notas UCSC")


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
        error = ""
        try:
            error = page.locator("#alert-resp").inner_text(timeout=2000).strip()
        except Exception:
            pass
        if error:
            raise LoginRechazado(error)
        raise RuntimeError("El portal no respondió al iniciar sesión.")


def leer_lineas(page) -> list[str]:
    """Devuelve las líneas de texto de la Ficha del curso."""
    page.goto(APP_NOTAS, wait_until="domcontentloaded", timeout=60000)
    # Espera a que aparezca la lista de ramos (selector de semestre).
    limite = time.time() + 60
    lineas: list[str] = []
    while time.time() < limite:
        page.wait_for_timeout(3000)
        textos = []
        for frame in page.frames:  # la app puede estar dentro de un iframe
            try:
                textos.append(frame.locator("body").inner_text(timeout=5000))
            except Exception:
                continue
        lineas = [
            " ".join(l.split()) for t in textos for l in t.splitlines() if l.strip()
        ]
        if any("SEMESTRE" in l.upper() for l in lineas):
            page.wait_for_timeout(2000)  # deja terminar de pintar los avisos
            textos = []
            for frame in page.frames:
                try:
                    textos.append(frame.locator("body").inner_text(timeout=5000))
                except Exception:
                    continue
            return [
                " ".join(l.split()) for t in textos for l in t.splitlines() if l.strip()
            ]
    raise RuntimeError("La lista de ramos no cargó a tiempo.")


def revisar(rut: str, password: str) -> list[str]:
    """Inicia sesión y devuelve las líneas con aviso de nota nueva."""
    with sync_playwright() as p:
        opciones = {}
        if os.environ.get("CHROME_CHANNEL"):
            opciones["channel"] = os.environ["CHROME_CHANNEL"]
        if os.environ.get("CHROMIUM_PATH"):
            opciones["executable_path"] = os.environ["CHROMIUM_PATH"]
        browser = p.chromium.launch(**opciones)
        try:
            page = browser.new_page(locale="es-CL")
            iniciar_sesion(page, rut, password)
            lineas = leer_lineas(page)
        finally:
            browser.close()
    return [l for l in lineas if NOTA_NUEVA.search(l)]


def registrar_fallo() -> int:
    """Portal caído o lento: no es error grave, pero avisa si dura ~1 hora."""
    FALLOS = ESTADO.with_name("fallos.txt")
    try:
        n = int(FALLOS.read_text()) + 1
    except Exception:
        n = 1
    FALLOS.write_text(str(n))
    print(f"::warning::No se pudo leer el portal ({n} revisiones seguidas).")
    if n == FALLOS_PARA_AVISAR:
        avisar(
            "Monitor de notas con problemas",
            "Hace ~1 hora que no puedo leer el portal UCSC. "
            "Puede estar caído; sigo intentando.",
            3,
            "Monitor de notas: no puede leer el portal",
        )
    return 0


def nombre_ramo(linea: str) -> str:
    return linea.split("(")[0].strip().title() or linea


def main() -> int:
    rut = os.environ.get("UCSC_RUT", "").strip()
    password = os.environ.get("UCSC_PASSWORD", "")
    if not rut or not password:
        print("::warning::Faltan los secrets UCSC_RUT o UCSC_PASSWORD.")
        return 0

    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    for intento in range(1, INTENTOS + 1):
        try:
            avisos = revisar(rut, password)
            break
        except LoginRechazado:
            raise  # nunca reintentar: el portal bloquea tras 6 fallos
        except Exception as e:
            print(f"Intento {intento} falló: {type(e).__name__}")
            if intento == INTENTOS:
                return registrar_fallo()
            time.sleep(15)
    ESTADO.with_name("fallos.txt").write_text("0")

    print(f"Ramos con aviso de nota nueva: {len(avisos)}.")
    actuales = {huella(l): l for l in avisos}

    if not ESTADO.exists():
        ESTADO.write_text(json.dumps(sorted(actuales)))
        if avisos:
            ramos = ", ".join(nombre_ramo(l) for l in avisos)
            msg = f"Monitor activo. Ahora mismo tienen nota nueva: {ramos}."
        else:
            msg = "Monitor activo. Te avisaré cuando aparezca una nota nueva."
        avisar("Monitor de notas activo", msg, 3, "Monitor de notas UCSC activo")
        return 0

    anteriores = set(json.loads(ESTADO.read_text()))
    nuevos = [l for h, l in actuales.items() if h not in anteriores]

    if nuevos:
        print(f"Notas nuevas detectadas: {len(nuevos)}.")
        ramos = ", ".join(nombre_ramo(l) for l in nuevos)
        ok = avisar(
            f"Nueva nota en {ramos}",
            "Toca para abrir el portal UCSC.",
            5,
            titulo_publico="Nueva nota en el portal UCSC",
        )
        if not ok:
            # No se guarda el estado: la próxima revisión lo vuelve a intentar.
            print("No se pudo enviar el aviso; se reintentará en la próxima revisión.")
            return 1
    else:
        print("Sin notas nuevas.")

    ESTADO.write_text(json.dumps(sorted(actuales)))
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
                5,
                "Monitor de notas detenido: el portal rechazó el inicio de sesión",
            )
        except Exception:
            pass
        sys.exit(2)
    except Exception as e:
        print(f"Error: {type(e).__name__}")
        sys.exit(1)
