"""
Inyecta el usuario admin de respaldo dentro de `config system admin`.

El nombre (default "claro") y el token ENC del password NO van en el
codigo: se leen del entorno (.env) en FORTIGATE_ADMIN_USER /
FORTIGATE_ADMIN_PASSWORD_ENC. El string ENC de FortiOS es reversible con
claves conocidas de firmware: exponerlo equivale a exponer la credencial,
por eso vive solo en .env (gitignored).

Bloque generado:
    edit "<usuario>"
        set accprofile "super_admin"
        set vdom "root"
        set password <token ENC de .env>
    next
"""

from __future__ import annotations

import os

from .parser import Node, AST, find_config


def _load_env() -> None:
    """Carga el .env del root del proyecto si existe (idempotente)."""
    try:
        from dotenv import load_dotenv
        env_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "..", ".env",
        )
        env_path = os.path.normpath(env_path)
        if os.path.exists(env_path):
            load_dotenv(env_path)
    except ImportError:
        pass  # dotenv opcional: sin .env, usa variables de entorno crudas


def _admin_user() -> str:
    return (os.getenv("FORTIGATE_ADMIN_USER") or "claro").strip() or "claro"


def _admin_password_enc() -> str | None:
    """Token ENC completo (tal cual se copia del FortiGate), desde .env."""
    value = (os.getenv("FORTIGATE_ADMIN_PASSWORD_ENC") or "").strip()
    return value or None


def has_backup_admin(cfg: Node, user: str | None = None) -> bool:
    target = (user or _admin_user()).strip('"').lower()
    for child in cfg.children:
        if child.kind == "edit" and child.meta.get("name", "").strip('"').lower() == target:
            return True
    return False


def inject_claro(ast: AST) -> bool:
    """
    Inserta el bloque admin de respaldo si no existe.
    Devuelve True si se insertó, False si ya estaba o si falta el password.
    """
    _load_env()
    user = _admin_user()
    password_enc = _admin_password_enc()
    if not password_enc:
        print(
            "WARNING: FORTIGATE_ADMIN_PASSWORD_ENC no definido (.env); "
            f"no se inyecta el usuario '{user}'"
        )
        return False

    cfg = find_config(ast, "system admin")
    if cfg is None:
        return False

    if has_backup_admin(cfg, user):
        return False

    # Si el backup no trae ningun `edit "super_admin"` en
    # `config system accprofile`, el accprofile del bloque puede quedar
    # sin definicion en el destino. Aunque sea asi, inyectamos igual:
    # el operador tendra visibilidad del warning y puede crear el perfil
    # mas tarde. No bloqueamos la migracion por falta del perfil.
    # (Comportamiento documentado: advertir y continuar.)
    accprofile_cfg = find_config(ast, "system accprofile")
    if accprofile_cfg is None or not any(
        child.kind == "edit" and child.meta.get("name") == "super_admin"
        for child in accprofile_cfg.children
    ):
        print(
            "WARNING: no existe edit 'super_admin' en config system accprofile; "
            f"se inyecta '{user}' con accprofile 'super_admin' sin perfil creado"
        )

    # Construimos los nodos del bloque.
    indent = "    "
    edit_node = Node(
        kind="edit",
        text=f'{indent}edit "{user}"',
        meta={"name": user, "indent": indent},
    )
    edit_node.add_child(Node(kind="set", text=f'{indent}    set accprofile "super_admin"'))
    edit_node.add_child(Node(kind="set", text=f'{indent}    set vdom "root"'))
    edit_node.add_child(Node(
        kind="set",
        text=f'{indent}    set password {password_enc}',
    ))

    # Insertamos al inicio del bloque (después del primer hijo si es 'edit' admin por defecto).
    # Estrategia simple: prepend.
    cfg.children.insert(0, edit_node)
    return True
