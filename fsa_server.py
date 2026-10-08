"""
fsa_server.py
=============
Kleiner lokaler Webserver fuer Field Service AI (nur Python-Standardbibliothek).

  python fsa_server.py              -> http://127.0.0.1:8000  (nur dieser Rechner)
  python fsa_server.py --lan        -> zusaetzlich im WLAN erreichbar (z.B. Techniker-App am Handy)
  python fsa_server.py --port 8080

Sicherheitsgrenzen:
  * Standard-Bind ausschliesslich 127.0.0.1; LAN nur mit ausdruecklichem --lan.
  * Ausgeliefert werden NUR Dateien aus einer Whitelist (HTML im Projektroot und
    push/). data/ (Excel, Kontaktdaten), Python-Code, Tests, venv sind nicht abrufbar.
  * POST /api/import (Excel hochladen + Dashboard neu bauen) ist nur von
    127.0.0.1 erlaubt -- auch im --lan-Modus --, nur .xlsx, max. 50 MB, und die
    Datei wird VOR dem Ersetzen validiert. Die Excel wird nie committet
    (data/*.xlsx ist gitignored).
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import tempfile
import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
XLSX_ZIEL = ROOT / "data" / "KI_gestuetzte_Planung.xlsx"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ERLAUBTE_ENDUNGEN = {".html", ".json", ".svg", ".js", ".png", ".ico"}
ERLAUBTE_UNTERORDNER = {"push"}

_import_lock = threading.Lock()


def lan_ip() -> str | None:
    """Beste Schaetzung der LAN-Adresse (kein Paket wird gesendet)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def ist_erlaubter_pfad(rel: str) -> bool:
    """Whitelist: Root-Dateien (nur HTML) und push/*."""
    teile = [t for t in rel.split("/") if t]
    if not teile or any(t.startswith(".") or t == ".." for t in teile):
        return False
    if len(teile) == 1:
        return Path(teile[0]).suffix.lower() == ".html"
    if len(teile) == 2 and teile[0] in ERLAUBTE_UNTERORDNER:
        return Path(teile[1]).suffix.lower() in ERLAUBTE_ENDUNGEN
    return False


def fuehre_import_aus() -> tuple[bool, str]:
    """Import + Dashboard in Subprozessen (saubere Prozess-Isolation)."""
    ausgabe: list[str] = []
    for modul in ("api.smax_cache", "reporting.dashboard"):
        r = subprocess.run([sys.executable, "-m", modul], cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=900)
        ausgabe.append(r.stdout[-4000:])
        if r.returncode != 0:
            ausgabe.append(r.stderr[-2000:])
            return False, "\n".join(ausgabe)
    return True, "\n".join(ausgabe)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    # -- GET: nur Whitelist ----------------------------------------------------
    def _rel(self) -> str:
        return self.path.split("?", 1)[0].split("#", 1)[0].lstrip("/")

    def do_GET(self):  # noqa: N802
        rel = self._rel() or "index.html"
        if not ist_erlaubter_pfad(rel):
            self.send_error(HTTPStatus.NOT_FOUND, "Nicht gefunden")
            return
        self.path = "/" + rel
        super().do_GET()

    def do_HEAD(self):  # noqa: N802
        rel = self._rel() or "index.html"
        if not ist_erlaubter_pfad(rel):
            self.send_error(HTTPStatus.NOT_FOUND, "Nicht gefunden")
            return
        self.path = "/" + rel
        super().do_HEAD()

    def list_directory(self, path):  # Verzeichnislisting deaktiviert
        self.send_error(HTTPStatus.NOT_FOUND, "Nicht gefunden")
        return None

    # -- POST /api/import ------------------------------------------------------
    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self) -> bool:
        """Schutz gegen DNS-Rebinding/CSRF: Host und Origin muessen localhost sein."""
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        if host not in ("localhost", "127.0.0.1"):
            return False
        origin = self.headers.get("Origin")
        if origin:
            o = origin.split("://", 1)[-1].split(":")[0].lower()
            return o in ("localhost", "127.0.0.1")
        return True

    def do_POST(self):  # noqa: N802
        if self._rel() != "api/import":
            self.send_error(HTTPStatus.NOT_FOUND, "Nicht gefunden")
            return
        if self.client_address[0] != "127.0.0.1" or not self._host_ok():
            self._json(403, {"ok": False, "fehler": "Import ist nur lokal auf diesem Rechner erlaubt."})
            return
        try:
            laenge = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            laenge = 0
        if laenge <= 0:
            self._json(400, {"ok": False, "fehler": "Keine Datei empfangen."})
            return
        if laenge > MAX_UPLOAD_BYTES:
            self._json(413, {"ok": False, "fehler": f"Datei zu gross (max. {MAX_UPLOAD_BYTES // 1024 // 1024} MB)."})
            return
        daten = self.rfile.read(laenge)
        if daten[:4] != b"PK\x03\x04":  # .xlsx ist ein ZIP-Container
            self._json(400, {"ok": False, "fehler": "Keine .xlsx-Datei (Dateikopf passt nicht)."})
            return

        from api.smax_validierung import validiere_smax_xlsx
        with _import_lock:
            with tempfile.NamedTemporaryFile(suffix=".xlsx", dir=XLSX_ZIEL.parent, delete=False) as tmp:
                tmp.write(daten)
                tmp_pfad = Path(tmp.name)
            try:
                probleme = validiere_smax_xlsx(tmp_pfad)
                if probleme:
                    self._json(422, {"ok": False, "fehler": "Format-Pruefung fehlgeschlagen",
                                     "probleme": probleme})
                    return
                if XLSX_ZIEL.exists():
                    vorher = XLSX_ZIEL.with_name("KI_gestuetzte_Planung.vorher.xlsx")
                    XLSX_ZIEL.replace(vorher)
                tmp_pfad.replace(XLSX_ZIEL)
            finally:
                tmp_pfad.unlink(missing_ok=True)
            ok, log = fuehre_import_aus()
        self._json(200 if ok else 500, {"ok": ok, "log": log,
                                        "fehler": None if ok else "Import fehlgeschlagen"})

    def log_message(self, fmt, *args):  # ruhiger, ohne Client-IP-Flut
        sys.stderr.write("[fsa] " + (fmt % args) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lokaler Field-Service-AI-Server")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--lan", action="store_true",
                    help="auch im lokalen Netzwerk erreichbar (Standard: nur 127.0.0.1)")
    args = ap.parse_args(argv)

    bind = "0.0.0.0" if args.lan else "127.0.0.1"
    try:
        server = ThreadingHTTPServer((bind, args.port), Handler)
    except OSError as e:
        print(f"FEHLER: Port {args.port} nicht verfuegbar ({e}). Laeuft schon ein Server? "
              f"Anderen Port mit --port waehlen.")
        return 1

    print(f"Dashboard:  http://localhost:{args.port}/dashboard.html")
    if args.lan:
        ip = lan_ip()
        print("LAN-Modus AKTIV -- im selben WLAN erreichbar (nur Whitelist-HTML, Import bleibt lokal).")
        if ip:
            print(f"Techniker-App (Handy): http://{ip}:{args.port}/techniker_app.html")
    print("Beenden mit Strg+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer beendet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
