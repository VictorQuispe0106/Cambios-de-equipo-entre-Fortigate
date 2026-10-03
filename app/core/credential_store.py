"""
Almacen de credenciales del admin de respaldo (FORTIGATE_ADMIN_USER /
FORTIGATE_ADMIN_PASSWORD_ENC) en el .env del root del proyecto.

El token ENC del password es una credencial reversible: NUNCA se devuelve
por ninguna API ni se escribe en logs. Las lecturas exponen solo un
booleano `token_configured`.

Las escrituras hacen upsert de SOLO esas dos claves en el .env del root
del proyecto, preservando todas las demas lineas y su orden, y actualizan
os.environ para que el proceso en marcha (engine/admin_injector) tome los
valores sin reiniciar.
"""

from __future__ import annotations

import os
import re

USER_KEY = "FORTIGATE_ADMIN_USER"
TOKEN_KEY = "FORTIGATE_ADMIN_PASSWORD_ENC"
DEFAULT_USER = "claro"

# Forma basica del token ENC de FortiOS: "ENC " + base64
_TOKEN_RE = re.compile(r"\AENC [A-Za-z0-9+/=]+\Z")


def _env_path(project_root: str) -> str:
    return os.path.join(project_root, ".env")


def _read_env_dict(path: str) -> dict:
    """Lee el .env a un dict simple (clave=valor), tolerante a espacios."""
    values: dict = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f.read().splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                values[key.strip()] = val.strip()
    except OSError:
        pass
    return values


def load_credentials(project_root: str) -> dict:
    """
    Credenciales tal como las ve el proceso. Nunca devuelve el token:
    solo `token_configured`. Si el .env no existe o la clave esta vacia,
    user="claro" y token_configured=False.
    """
    values = _read_env_dict(_env_path(project_root))
    user = (values.get(USER_KEY) or "").strip() or DEFAULT_USER
    token_configured = bool((values.get(TOKEN_KEY) or "").strip())
    return {"user": user, "token_configured": token_configured}


def save_credentials(project_root: str, user: str, enc_token: str) -> dict:
    """
    Valida y persiste las credenciales en el .env del project_root
    (upsert de las dos claves, preservando el resto de lineas y su
    orden), y actualiza os.environ para el proceso en marcha.
    Lanza ValueError con mensaje en espanol ante entrada invalida.
    """
    if not isinstance(user, str) or not user.strip():
        raise ValueError("El usuario admin no puede estar vacio")
    if not isinstance(enc_token, str) or not _TOKEN_RE.match(enc_token.strip()):
        raise ValueError(
            "El token debe tener la forma 'ENC <base64>' (copiado del FortiGate)"
        )

    clean_user = user.strip()
    clean_token = enc_token.strip()

    path = _env_path(project_root)
    lines: list = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        pass

    new_entries = {USER_KEY: clean_user, TOKEN_KEY: clean_token}
    seen: set = set()
    out: list = []
    for raw in lines:
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in new_entries:
                out.append(f"{key}={new_entries[key]}")
                seen.add(key)
                continue
        out.append(raw)
    # Claves que no existian: se agregan al final (higiene: una sola vez)
    for key, val in new_entries.items():
        if key not in seen:
            out.append(f"{key}={val}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + ("\n" if out else ""))

    os.environ[USER_KEY] = clean_user
    os.environ[TOKEN_KEY] = clean_token

    return {"user": clean_user, "token_configured": True}
