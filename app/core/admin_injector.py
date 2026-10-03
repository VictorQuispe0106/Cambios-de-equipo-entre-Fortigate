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
from typing import List

from .parser import Node, AST, find_config


CLARO_BLOCK_LINES: List[str] = [
    'edit "claro"',
    '    set accprofile "super_admin"',
    '    set vdom "root"',
    '    set password [REDACTED]',
    "next",
]


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