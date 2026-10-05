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

from .parser import Node, AST, find_config, parse


def find_config_from(node: Node, name: str) -> Optional[Node]:
    """find_config anidado desde un nodo config dado (ej. buscar 'zone'
    dentro de 'system sdwan')."""
    for child in node.children:
        if child.kind == "config" and child.meta.get("name") == name:
            return child
    for child in node.children:
        if child.kind in ("config", "edit"):
            for sub in child.children:
                if sub.kind == "config" and sub.meta.get("name") == name:
                    return sub
    return None


_NAME_CHARS = re.compile(r"[A-Za-z0-9_.\-]")

_SUFFIX_RE = re.compile(r"^(.*?)((?:\.\d+)+)$")


def _split_name_suffix(matched: str) -> Tuple[str, str]:
    """Separa un nombre con sufijo de subinterfaz: 'port1.100' -> ('port1', '.100')."""
    m = _SUFFIX_RE.match(matched)
    if m:
        return m.group(1), m.group(2)
    return matched, ""

def _build_pattern(old: str) -> re.Pattern:
    escaped = re.escape(old)
    return re.compile(rf"(?<![A-Za-z0-9_.\-]){escaped}(?![A-Za-z0-9_.\-])")


def _build_combined_pattern(mapping: Dict[str, str]):
    """
    Construye UNA regex con alternacion de todas las claves del mapping
    (ordenadas de mas larga a mas corta), con captura del nombre viejo.
    El callable de reemplazo nunca re-escanea el texto de reemplazo:
    un solo pase evita corrupcion en mapeos encadenados
    (ej. wan3->port4 y port4->port5).
    """
    keys = sorted(mapping.keys(), key=len, reverse=True)
    if not keys:
        return None
    alts = "|".join(f"(?P<k{i}>{re.escape(k)})" for i, k in enumerate(keys))
    # Los refs a subinterfaces fisicas usan sufijo .N (ej. port1.100):
    # se captura junto con la clave para renombrar old.subN -> new.subN
    return re.compile(rf"(?<![A-Za-z0-9_.\-])(?:{alts})((?:\.\d+)+)?(?![A-Za-z0-9_.\-])")


def _make_replacer(mapping: Dict[str, str], counts: Dict[str, int]):
    """Callable de reemplazo para el pase unico: sustituye cada coincidencia
    por su mapping correspondiente y acumula el conteo por nombre viejo."""
    pattern = _build_combined_pattern(mapping)
    keys = sorted(mapping.keys(), key=len, reverse=True)

    def repl(match: re.Match) -> str:
        matched = match.group(0)
        suffix = match.group(len(keys) + 1) or ""
        # base = la clave que matcheo (alternativas ordenadas mas larga primero)
        base = matched[: len(matched) - len(suffix)] if suffix else matched
        counts[base] += 1
        return mapping[base] + suffix

    return repl, pattern


_INTERFACE_REF_KEYS = {
    "srcintf", "dstintf", "interface", "extintf",
    "local-interface", "remote-interface", "ipsec-interface",
}


def rename_references(ast: AST, mapping: Dict[str, str]) -> Dict[str, int]:
    """
    Recorre el AST y reemplaza referencias a nombres viejos por los nuevos
    en UN SOLO pase (el texto de reemplazo nunca se re-escanea, evitando
    corrupcion con mapeos encadenados).
    Devuelve un dict {nombre_viejo: #_sustituciones_realizadas}.
    """
    counts: Dict[str, int] = {old: 0 for old in mapping}
    repl, pattern = _make_replacer(mapping, counts)
    if pattern is None:
        return counts
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
                new_t = pattern.sub(repl, old_t)
                if new_t != old_t:
                    child.text = new_t
                continue

            if child.kind == "edit":
                walk(child)
                continue

            walk(child)

    walk(ast.nodes[0])
    return counts


_NONINTERFACE_VALUES = {"*", "any", "none"}


def _is_macro_or_wildcard(value: str) -> bool:
    """True para valores que nunca son nombres de interfaz fisica: macros
    ("$(VDOM_LINKS)"), wildcards ("*") y placeholders de plantilla."""
    return bool(
    value in _NONINTERFACE_VALUES
    or "(" in value
    or "$" in value
    or "*" in value
    or "?" in value
)


def find_unrenamed_references(
    text: str, mapping: Dict[str, str]
) -> List[Tuple[int, str, str]]:
    """
    Busca referencias a nombres viejos que no fueron renombradas.
    Returns: Lista de (line_number, interface_name, line_text).
    """
    patterns = {old: _build_pattern(old) for old in mapping if old not in mapping.values()}
    results = []
    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for old_name in mapping:
            # Un nombre que tambien es valor del mapping es producto del
            # renombrado en un solo pase, no una referencia no renombrada.
            if old_name in patterns and patterns[old_name].search(line):
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
                if ref in _NONINTERFACE_VALUES or _is_macro_or_wildcard(ref):
                    continue
                if ref not in defined_interfaces:
                    results.append((line_no, ref, line))
    return results


def get_zone_names(text: str) -> Set[str]:
    """Extrae los nombres de zonas definidos en el texto:
      - config system zone (edits directos)
      - config system sdwan -> config zone (nested, SD-WAN zones)
    """
    ast = parse(text)
    zones: Set[str] = set()
    for cfg_name, nested in (("system zone", False), ("system sdwan", True)):
        cfg = find_config(ast, cfg_name)
        if cfg is None:
            continue
        if not nested:
            for edit in cfg.children:
                if edit.kind == "edit":
                    name = edit.meta.get("name", "")
                    if name:
                        zones.add(name)
        else:
            zone_block = find_config_from(cfg, "zone")
            if zone_block is None:
                continue
            for edit in zone_block.children:
                if edit.kind == "edit":
                    name = edit.meta.get("name", "")
                    if name:
                        zones.add(name)
    return zones


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
