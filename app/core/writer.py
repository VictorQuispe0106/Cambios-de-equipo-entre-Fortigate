"""
Serializador: AST -> texto .conf preservando formato.
"""

from __future__ import annotations
from .parser import Node, AST


def render(ast: AST) -> str:
    """Renderiza el AST completo a texto."""
    out: list[str] = []

    def walk(node: Node):
        for child in node.children:
            kind = child.kind
            if kind == "blank":
                out.append(child.text)
                continue
            if kind == "comment":
                out.append(child.text)
                continue
            if kind == "raw" or kind == "orphan_end" or kind == "orphan_next":
                out.append(child.text)
                continue
            if kind == "set":
                out.append(child.text)
                continue
            if kind == "config":
                out.append(child.text)
                walk(child)
                indent = child.meta.get("indent", "")
                out.append(f"{indent}end")
                continue
            if kind == "edit":
                out.append(child.text)
                walk(child)
                indent = child.meta.get("indent", "")
                out.append(f"{indent}next")
                continue
            out.append(child.text)

    walk(ast.nodes[0])
    if not out:
        return ""
    return "\n".join(out) + "\n"