"""
Renombra referencias a interfaces fisicas en todo el AST.

Despues del mapper, los nodos edit dentro de config system interface
ya tienen los nombres nuevos. Pero muchas otras secciones
(policies, zones, routes, switch-interface, aggregate member, etc.)
contienen menciones literales al nombre viejo.

Estrategia: recorremos todos los nodos AST y, para cualquier nodo
que NO sea el edit que estamos renombrando, sustituimos dentro de
sus lineas set cualquier coincidencia exacta (palabra completa)
del nombre viejo por el nuevo.
"""

from __future__ import annotations
import re
from typing import Dict, List, Set, Tuple

from .parser import Node, AST, find_config


_NAME_CHARS = re.compile(r"[A-Za-z0-9_.\-]")


def _build_pattern(old: str) -> re.Pattern:
    escaped = re.escape(old)
    return re.compile(rf"(?<![A-Za-z0-9_.\-]){escaped}(?![A-Za-z0-9_.\-])")


_INTERFACE_REF_KEYS = {
    "srcintf", "dstintf", "interface", "extintf",
    "local-interface", "remote-interface", "ipsec-interface",
}


def rename_references(ast: AST, mapping: Dict[str, str]) -> Dict[str, int]:
    """
    Recorre el AST y reemplaza referencias a nombres viejos por los nuevos.
    Devuelve un dict {nombre_viejo: #_sustituciones_realizadas}.
    """
    counts: Dict[str, int] = {old: 0 for old in mapping}
    patterns = {old: _build_pattern(old) for old in mapping}
    cfg_interface = find_config(ast, "system interface")

    def walk(node: Node):
        for child in node.children:
            if child.kind in ("set", "raw", "comment", "blank"):
                if not child.text:
                    continue
                if (
                    cfg_interface is not None
                    and node is cfg_interface
                    and child.kind == "set"
                ):
                    continue
                old_t = child.text
                new_t = old_t
                for old, new in mapping.items():
                    new_t = patterns[old].sub(new, new_t)
                if new_t != old_t:
                    for old in mapping:
                        before = len(patterns[old].findall(old_t))
                        after = len(patterns[old].findall(new_t))
                        counts[old] += max(0, before - after)
                    child.text = new_t
                continue

            if child.kind == "edit":
                walk(child)
                continue

            walk(child)

    walk(ast.nodes[0])
    return counts


def find_unrenamed_references(
    text: str, mapping: Dict[str, str]
) -> List[Tuple[int, str, str]]:
    """
    Busca referencias a nombres viejos que no fueron renombradas.
    Returns: Lista de (line_number, interface_name, line_text).
    """
    patterns = {old: _build_pattern(old) for old in mapping}
    results = []
    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for old_name in mapping:
            if patterns[old_name].search(line):
                results.append((line_no, old_name, line))
    return results


def find_orphaned_references(
    text: str, defined_interfaces: Set[str]
) -> List[Tuple[int, str, str]]:
    """
    Busca interfaces referenciadas en set commands que no estan definidas.
    Returns: Lista de (line_number, interface_name, line_text).
    """
    results = []
    in_interface_config = False
    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped == "config system interface":
            in_interface_config = True
            continue
        elif stripped == "end" and in_interface_config:
            in_interface_config = False
            continue
        if in_interface_config:
            continue
        if not stripped.startswith("set "):
            continue
        parts = stripped[4:].split(None, 1)
        if len(parts) < 2:
            continue
        key = parts[0]
        value = parts[1].strip()
        if key in _INTERFACE_REF_KEYS:
            refs = re.findall(r'"([^"]+)"', value)
            if not refs:
                refs = [value.split()[0]] if value else []
            for ref in refs:
                if ref not in defined_interfaces:
                    results.append((line_no, ref, line))
    return results


def get_interface_names_from_config(text: str) -> Set[str]:
    """Extrae todos los nombres de interfaces definidos en config system interface."""
    interfaces = set()
    in_interface_config = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "config system interface":
            in_interface_config = True
            continue
        elif stripped == "end" and in_interface_config:
            in_interface_config = False
            continue
        if in_interface_config and stripped.startswith("edit "):
            name = stripped[len("edit "):].strip().strip('"')
            if name:
                interfaces.add(name)
    return interfaces
