"""
Clasificador de interfaces dentro de `config system interface`.

Devuelve una lista ordenada de registros con:
  - node: el nodo AST del edit
  - name: nombre actual (ej. "wan1", "a", "internal3", "naf.root")
  - type: uno de {wan, mgmt, dmz, ha, lan_port, modem, logical}
  - is_physical: True si type physical
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional

from .parser import Node, AST, find_config, get_set_value


@dataclass
class InterfaceInfo:
    node: Node
    name: str
    iftype: str
    is_physical: bool
    alias: Optional[str] = None
    role: Optional[str] = None
    vrf: Optional[str] = None
    dedicated_to: Optional[str] = None

    @property
    def label(self) -> str:
        return self.name


_LOGICAL_TYPES = {"tunnel", "aggregate", "vdom-link", "vlan", "switch"}


def classify(ast: AST) -> List[InterfaceInfo]:
    cfg = find_config(ast, "system interface")
    if cfg is None:
        return []

    result: List[InterfaceInfo] = []
    for edit in cfg.children:
        if edit.kind != "edit":
            continue
        name = edit.meta.get("name", "")
        if not name:
            continue

        iftype = (get_set_value(edit, "type") or "").strip().strip('"')
        alias = get_set_value(edit, "alias")
        role = get_set_value(edit, "role")
        vrf = get_set_value(edit, "vrf")
        dedicated_to = get_set_value(edit, "dedicated-to")
        is_physical = iftype == "physical"

        # Clasificacion
        kind = "logical"

        # 1. WAN
        if name.lower().startswith("wan"):
            kind = "wan"
        # 2. HA
        elif name.lower() in ("ha1", "ha2"):
            kind = "ha"
        # 3. DMZ explicita (por nombre o role)
        elif name.lower() == "dmz" or (role and role.strip('"') == "dmz"):
            kind = "dmz"
        # 4. Management: por nombre canonico, dedicated-to, alias o vrf
        elif (
            name.lower() == "mgmt"
            or (dedicated_to and dedicated_to.strip('"') == "management")
            or (alias and any(tok in alias.upper() for tok in ("VRF_GESTION", "GESTION")))
            or vrf
        ):
            kind = "mgmt"
        # 5. Modem
        elif name.lower() == "modem":
            kind = "modem"
        # 6. Logicas puras
        elif iftype in _LOGICAL_TYPES:
            kind = "logical"
        # 7. Fisica sin clasificar: puerto LAN
        elif is_physical:
            kind = "lan_port"

        result.append(InterfaceInfo(
            node=edit,
            name=name,
            iftype=iftype,
            is_physical=is_physical,
            alias=alias,
            role=role,
            vrf=vrf,
            dedicated_to=dedicated_to,
        ))
        # Sobrescribimos el tipo en meta para uso del mapper
        edit.meta["_iftype"] = iftype
        edit.meta["_class"] = kind

    return result


def attach_class(ast: AST, info: List[InterfaceInfo]) -> None:
    """Vuelve a aplicar la clasificacion escribiendo _class en meta (util tras mutaciones)."""
    classify(ast)