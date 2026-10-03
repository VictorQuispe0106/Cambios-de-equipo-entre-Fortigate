"""
Parser para archivos .conf de FortiOS.

FortiOS usa una sintaxis jerarquica con bloques config/ end, edit/ next y set clave valor.
Este modulo convierte el archivo en un AST (arbol de sintaxis abstracta) que preserva:
  - Comentarios (lineas que empiezan con #)
  - Lineas vacias (como nodos 'blank')
  - Orden de los hijos
  - Texto exacto de cada linea (incluyendo indentacion original)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Node:
    kind: str
    text: str = ""
    children: List["Node"] = field(default_factory=list)
    parent: Optional["Node"] = None
    meta: dict = field(default_factory=dict)

    def add_child(self, node: "Node") -> "Node":
        node.parent = self
        self.children.append(node)
        return node


@dataclass
class AST:
    nodes: List[Node] = field(default_factory=list)


def parse(text: str) -> AST:
    """
    Parsea el contenido de un .conf FortiOS y devuelve un AST.

    Algoritmo:
      - Usamos un stack de "bloques" (config, edit).
      - Cada linea se anexa como nodo al bloque actual, manteniendo su texto literal.
      - 'config X' abre un nuevo bloque config y lo apila.
      - 'end' cierra el bloque config en el tope del stack.
      - 'edit X' abre un nuevo bloque edit y lo apila.
      - 'next' cierra el bloque edit en el tope del stack.
      - 'set ...' / comentarios / blancos se anexan al bloque actual.
    """
    ast = AST()
    root = Node(kind="root")
    ast.nodes.append(root)

    stack: List[Node] = [root]

    for raw in text.splitlines():
        stripped = raw.strip()
        indent = raw[: len(raw) - len(stripped)]

        # Comentario
        if stripped.startswith("#"):
            stack[-1].add_child(Node(kind="comment", text=raw))
            continue

        # Linea vacia
        if stripped == "":
            stack[-1].add_child(Node(kind="blank", text=raw))
            continue

        # config
        if stripped.startswith("config ") and not stripped.startswith("config-"):
            name = stripped[len("config "):].strip()
            node = Node(kind="config", text=raw, meta={"name": name, "indent": indent})
            stack[-1].add_child(node)
            stack.append(node)
            continue

        # end -> cierra config
        if stripped == "end":
            if len(stack) > 1 and stack[-1].kind == "config":
                stack.pop()
            else:
                stack[-1].add_child(Node(kind="orphan_end", text=raw))
            continue

        # edit
        if stripped.startswith("edit ") and not stripped.startswith("editor"):
            edit_name = stripped[len("edit "):].strip().strip('"')
            edit_node = Node(kind="edit", text=raw, meta={"name": edit_name, "indent": indent})
            stack[-1].add_child(edit_node)
            stack.append(edit_node)
            continue

        # next -> cierra edit
        if stripped.startswith("next"):
            if len(stack) > 1 and stack[-1].kind == "edit":
                stack.pop()
            else:
                stack[-1].add_child(Node(kind="orphan_next", text=raw))
            continue

        # set / unset
        if stripped.startswith("set ") or stripped.startswith("unset "):
            stack[-1].add_child(Node(kind="set", text=raw))
            continue

        # Cualquier otra cosa: nodo raw
        stack[-1].add_child(Node(kind="raw", text=raw))

    return ast


def find_config(ast: AST, name: str) -> Optional[Node]:
    """
    Busca un nodo config por nombre exacto.

    Prioriza la coincidencia a nivel raiz. Si no existe, busca recursivamente
    dentro de bloques edit (backups multi-vdom: `config vdom` -> `edit root` ->
    `config system admin`, etc.), hasta una profundidad razonable.
    """
    def _search(children, allow_nested: bool) -> Optional[Node]:
        for node in children:
            if node.kind == "config" and node.meta.get("name") == name:
                return node
        if not allow_nested:
            return None
        for node in children:
            # Descendemos solo por config y edit (los configs solo se anidan
            # dentro de edits en backups multi-vdom).
            if node.kind in ("config", "edit"):
                found = _search(node.children, allow_nested=True)
                if found is not None:
                    return found
        return None

    root_children = ast.nodes[0].children
    # Preferir la coincidencia a nivel raiz si existe
    found = _search(root_children, allow_nested=False)
    if found is not None:
        return found
    return _search(root_children, allow_nested=True)


def get_set_value(node: Node, key: str) -> Optional[str]:
    """Devuelve el valor de la primera linea `set key value` dentro de un nodo (o None)."""
    for child in node.children:
        if child.kind == "set":
            text = child.text.strip()
            if text.startswith("set "):
                parts = text[4:].split(None, 1)
                if parts and parts[0] == key:
                    return parts[1] if len(parts) > 1 else ""
    return None


def remove_set(node: Node, key: str) -> int:
    """Elimina todas las lineas `set key ...` de un nodo. Devuelve cantidad eliminada."""
    removed = 0
    keep: List[Node] = []
    for child in node.children:
        if child.kind == "set":
            text = child.text.strip()
            if text.startswith("set "):
                parts = text[4:].split(None, 1)
                if parts and parts[0] == key:
                    removed += 1
                    continue
        keep.append(child)
    node.children = keep
    return removed