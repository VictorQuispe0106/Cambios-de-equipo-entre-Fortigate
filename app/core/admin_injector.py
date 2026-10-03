"""
Inyecta el usuario admin 'claro' dentro de `config system admin`.

Bloque (literal del AGENTS.md):
    edit "claro"
        set accprofile "super_admin"
        set vdom "root"
        set password [REDACTED]
    next
"""

from __future__ import annotations

from .parser import Node, AST, find_config


def _has_claro(cfg: Node) -> bool:
    for child in cfg.children:
        if child.kind == "edit" and child.meta.get("name") == "claro":
            return True
    return False


def inject_claro(ast: AST) -> bool:
    """
    Inserta el bloque admin 'claro' si no existe.
    Devuelve True si se insertó, False si ya estaba.
    """
    cfg = find_config(ast, "system admin")
    if cfg is None:
        return False

    if _has_claro(cfg):
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
            "se inyecta claro con accprofile 'super_admin' sin perfil creado"
        )

    # Construimos los nodos del bloque.
    indent = "    "
    edit_node = Node(
        kind="edit",
        text=f'{indent}edit "claro"',
        meta={"name": "claro", "indent": indent},
    )
    edit_node.add_child(Node(kind="set", text=f'{indent}    set accprofile "super_admin"'))
    edit_node.add_child(Node(kind="set", text=f'{indent}    set vdom "root"'))
    edit_node.add_child(Node(
        kind="set",
        text=f'{indent}    set password [REDACTED]',
    ))

    # Insertamos al inicio del bloque (después del primer hijo si es 'edit' admin por defecto).
    # Estrategia simple: prepend.
    cfg.children.insert(0, edit_node)
    return True