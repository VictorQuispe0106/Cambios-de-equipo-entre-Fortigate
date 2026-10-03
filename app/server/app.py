"""
Servidor HTTP local para la UI web.

Endpoints:
  GET  /                          -> web/index.html
  GET  /static/<archivo>          -> archivos estaticos (CSS, JS)
  GET  /sample/<archivo>          -> backups de ejemplo
  GET  /api/health                -> health check
  POST /api/preview-template      -> analiza el backup destino y devuelve el layout
  POST /api/dry-run               -> simula el proceso sin generar output
  POST /api/process               -> procesa (requiere 'text' y 'template')
  POST /api/download              -> devuelve el .conf resultante como descarga

Uso:
  python server/app.py 8765
"""

from __future__ import annotations
import json
import os
import sys
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEB_DIR = os.path.join(ROOT, "web")
SAMPLES_DIR = os.path.dirname(ROOT)

sys.path.insert(0, ROOT)

from core.engine import (
    run_pipeline, validate_balance, preview_reassignments,
    dry_run, compute_diff_stats,
)
from core.interface_mapper import Reassignment
from core.template_parser import extract_layout, summarize
from core.config_validator import validate_config, format_validation_report


def _free_port(preferred: int) -> int:
    for port in (preferred, preferred + 2, preferred + 4, preferred + 6, preferred + 8):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return preferred


class Handler(BaseHTTPRequestHandler):
    server_version = "FortiGateMigrator/4.0"

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, obj: dict, status: int = 200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, status: int = 200, content_type: str = "text/plain; charset=utf-8"):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: str, content_type: str):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length > 0 else b""

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path

        if path == "/" or path == "/index.html":
            return self._send_file(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")

        if path.startswith("/static/"):
            rel = path[len("/static/"):]
            full = os.path.normpath(os.path.join(WEB_DIR, rel))
            if not full.startswith(os.path.normpath(WEB_DIR)):
                return self.send_error(403)
            ext = os.path.splitext(full)[1].lower()
            ctype = {
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".svg": "image/svg+xml",
            }.get(ext, "application/octet-stream")
            return self._send_file(full, ctype)

        if path.startswith("/sample/"):
            rel = path[len("/sample/"):]
            if not rel or "/" in rel or ".." in rel:
                return self.send_error(400)
            full = os.path.normpath(os.path.join(SAMPLES_DIR, rel))
            if not full.startswith(os.path.normpath(SAMPLES_DIR)):
                return self.send_error(403)
            return self._send_file(full, "text/plain; charset=utf-8")

        if path == "/api/health":
            return self._send_json({"ok": True})

        self.send_error(404)

    def do_POST(self):
        url = urlparse(self.path)
        path = url.path

        if path == "/api/preview-template":
            return self._handle_preview_template()
        if path == "/api/dry-run":
            return self._handle_dry_run()
        if path == "/api/process":
            return self._handle_process()
        if path == "/api/download":
            return self._handle_download()

        self.send_error(404)

    def _handle_preview_template(self):
        try:
            payload = json.loads(self._read_body().decode("utf-8") or "{}")
        except json.JSONDecodeError as e:
            return self._send_json({"error": f"JSON invalido: {e}"}, 400)

        template_text = payload.get("template", "")
        src_text = payload.get("text", "")

        if not isinstance(template_text, str) or not template_text.strip():
            return self._send_json({"error": "Falta el campo 'template'"}, 400)

        try:
            layout = extract_layout(template_text)
        except ValueError as e:
            return self._send_json({"error": str(e)}, 400)

        response = {
            "ok": True,
            "model_hint": layout.model_hint,
            "wan_count": layout.wan_count,
            "lan_count": layout.lan_count,
            "lan_names": layout.lan_names,
            "has_mgmt": layout.has_mgmt,
            "has_dmz": layout.has_dmz,
            "has_ha": layout.has_ha,
            "logical_count": len(layout.logical_names),
            "modem_count": len(layout.modem_names),
            "summary": summarize(layout),
            "slots": list(layout.slots),
            "excedentes": [],
            "would_be_discarded_if_no_manual": [],
        }

        if src_text and isinstance(src_text, str) and src_text.strip():
            try:
                excedentes, would_discard = preview_reassignments(src_text, template_text)
                response["excedentes"] = excedentes
                response["would_be_discarded_if_no_manual"] = would_discard
            except Exception as e:
                response["excedent_error"] = str(e)

        return self._send_json(response)

    def _handle_dry_run(self):
        """Simula el proceso sin generar output final."""
        try:
            payload = json.loads(self._read_body().decode("utf-8") or "{}")
        except json.JSONDecodeError as e:
            return self._send_json({"error": f"JSON invalido: {e}"}, 400)

        text = payload.get("text", "")
        template = payload.get("template", "")

        if not isinstance(text, str) or not text:
            return self._send_json({"error": "Falta 'text' (backup origen)"}, 400)
        if not isinstance(template, str) or not template.strip():
            return self._send_json({"error": "Falta 'template' (backup destino)"}, 400)

        inject_admin = bool(payload.get("inject_admin", True))

        ra_raw = payload.get("reassignments", [])
        reassignments = self._parse_reassignments(ra_raw)

        try:
            result = dry_run(text, template, inject_admin=inject_admin,
                             reassignments=reassignments if reassignments else None)
        except ValueError as e:
            return self._send_json({"error": f"Error en la plantilla: {e}"}, 400)
        except Exception as e:
            return self._send_json({"error": f"Error en dry-run: {e}"}, 500)

        diff_stats = compute_diff_stats(text, result.output_text)

        return self._send_json({
            "ok": True,
            "dry_run": True,
            "detected_model": result.detected_model,
            "target_model_hint": result.layout.model_hint if result.layout else None,
            "target_summary": summarize(result.layout) if result.layout else "",
            "mapping": result.mapping,
            "log": result.log,
            "warnings": result.warnings,
            "rename_counts": result.rename_counts,
            "claro_injected": result.claro_injected,
            "reassignments": [
                {
                    "src_name": r.src_name,
                    "src_kind": r.src_kind,
                    "target_slot": r.target_slot,
                    "original_role": r.original_role,
                }
                for r in result.reassignments
            ],
            "would_be_discarded": result.would_be_discarded,
            "diff_stats": diff_stats,
            "validation": {
                "is_valid": result.validation.is_valid if result.validation else None,
                "errors": result.validation.errors if result.validation else [],
                "warnings_count": len(result.validation.warnings) if result.validation else 0,
                "stats": result.validation.stats if result.validation else {},
            } if result.validation else None,
            "unrenamed_refs_count": len(result.unrenamed_refs),
            "orphaned_refs_count": len(result.orphaned_refs),
        })

    def _handle_process(self):
        try:
            payload = json.loads(self._read_body().decode("utf-8") or "{}")
        except json.JSONDecodeError as e:
            return self._send_json({"error": f"JSON invalido: {e}"}, 400)

        text = payload.get("text", "")
        template = payload.get("template", "")

        if not isinstance(text, str) or not text:
            return self._send_json({"error": "Falta 'text' (backup origen)"}, 400)
        if not isinstance(template, str) or not template.strip():
            return self._send_json({"error": "Falta 'template' (backup destino)"}, 400)

        inject_admin = bool(payload.get("inject_admin", True))

        ra_raw = payload.get("reassignments", [])
        reassignments = self._parse_reassignments(ra_raw)

        try:
            result = run_pipeline(text, template, inject_admin=inject_admin,
                                  reassignments=reassignments if reassignments else None)
        except ValueError as e:
            return self._send_json({"error": f"Error en la plantilla: {e}"}, 400)
        except Exception as e:
            return self._send_json({"error": f"Error procesando: {e}"}, 500)

        issues = validate_balance(result.output_text)
        diff_stats = compute_diff_stats(text, result.output_text)

        return self._send_json({
            "ok": True,
            "detected_model": result.detected_model,
            "target_model_hint": result.layout.model_hint if result.layout else None,
            "target_summary": summarize(result.layout) if result.layout else "",
            "target_slots": result.layout.slots if result.layout else [],
            "mapping": result.mapping,
            "log": result.log,
            "warnings": result.warnings,
            "rename_counts": result.rename_counts,
            "claro_injected": result.claro_injected,
            "reassignments": [
                {
                    "src_name": r.src_name,
                    "src_kind": r.src_kind,
                    "target_slot": r.target_slot,
                    "original_role": r.original_role,
                }
                for r in result.reassignments
            ],
            "would_be_discarded": result.would_be_discarded,
            "balance_issues": issues,
            "output_text": result.output_text,
            "diff_stats": diff_stats,
            "validation": {
                "is_valid": result.validation.is_valid if result.validation else None,
                "errors": result.validation.errors if result.validation else [],
                "warnings": result.validation.warnings if result.validation else [],
                "stats": result.validation.stats if result.validation else {},
                "report": format_validation_report(result.validation) if result.validation else "",
            } if result.validation else None,
            "unrenamed_refs": [
                {"line": ln, "interface": iface, "text": txt}
                for ln, iface, txt in result.unrenamed_refs
            ],
            "orphaned_refs": [
                {"line": ln, "interface": iface, "text": txt}
                for ln, iface, txt in result.orphaned_refs
            ],
        })

    def _handle_download(self):
        try:
            payload = json.loads(self._read_body().decode("utf-8") or "{}")
        except json.JSONDecodeError as e:
            return self._send_json({"error": f"JSON invalido: {e}"}, 400)

        text = payload.get("text", "")
        filename = payload.get("filename", "backup_migrado.conf")
        if not text:
            return self._send_json({"error": "Falta 'text'"}, 400)

        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def _parse_reassignments(self, ra_raw) -> list:
        reassignments = []
        if isinstance(ra_raw, list):
            for item in ra_raw:
                if not isinstance(item, dict):
                    continue
                try:
                    reassignments.append(Reassignment(
                        src_name=str(item.get("src_name", "")),
                        src_kind=str(item.get("src_kind", "physical_other")),
                        target_slot=str(item.get("target_slot", "")),
                        original_role=item.get("original_role"),
                    ))
                except Exception:
                    pass
        return reassignments


def main(argv):
    preferred = 8765
    if len(argv) >= 2:
        try:
            preferred = int(argv[1])
        except ValueError:
            pass

    port = _free_port(preferred)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)

    print(f"===================================================")
    print(f" Cambio de Equipo FortiGate - servidor local")
    print(f" URL:  http://localhost:{port}")
    print(f"===================================================")
    print(f" (Cierra esta ventana para detener el servidor)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main(sys.argv)
