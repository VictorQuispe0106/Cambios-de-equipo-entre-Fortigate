"""
Parser de la plantilla del modelo destino.

A partir de un .conf de FortiGate (un backup de referencia del modelo al que
se quiere pasar), extrae:
  - has_wan: bool
  - wan_count: int
  - has_mgmt: bool
  - has_dmz: bool
  - has_ha: bool
  - lan_names: [str]   ej. ["port1", "port2", ..., "portN"] en orden canonico
  - logical_names: [str]  nombres de interfaces logicas a conservar
  - modem_names: [str]    nombres de interfaces modem (fisicas)
  - model_hint: Optional[str]  (del #config-version= si esta disponible)

La salida se usa en interface_mapper.py para construir el DestinationLayout.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import List, Optional

from .parser import parse, find_config, get_set_value
from .model_detector import detect_model
from .interface_mapper import DestinationLayout


def _explicit_metadata_class(role: Optional[str], dedicated_to: Optional[str],
                             alias: Optional[str], vrf: Optional[str]) -> Optional[str]:
    """T2: clase explicita segun metadata FortiOS. Priman los metadatos
    (set role, set dedicated-to, set vrf, alias GESTION) sobre el nombre.
    Devuelve "wan"/"dmz"/"lan"/"mgmt" o None si no hay metadata explicita."""
    r = (role or "").strip().strip('"').lower()
    if r in ("wan", "dmz", "lan"):
        return r
    d = (dedicated_to or "").strip().strip('"').lower()
    if d == "management" or vrf or (alias and "GESTION" in alias.upper()):
        return "mgmt"
    return None


@dataclass
class _LegacyDestinationLayout:
    """Layout intermedio con campos extra para preview."""
    model_hint: Optional[str] = None
    wan_count: int = 0
    has_mgmt: bool = False
    has_dmz: bool = False
    has_ha: bool = False
    lan_names: List[str] = field(default_factory=list)
    logical_names: List[str] = field(default_factory=list)
    modem_names: List[str] = field(default_factory=list)
    _misc_physicals: List[str] = field(default_factory=list)
    # T1: nombres REALES recolectados por clase especial (no literales)
    dmz_names: List[str] = field(default_factory=list)
    mgmt_names: List[str] = field(default_factory=list)
    ha_names: List[str] = field(default_factory=list)

    @property
    def lan_count(self) -> int:
        return len(self.lan_names)


_VERSION_RE = re.compile(r"#config-version=(FGT?\d+[A-Z])")


def _classify_destination_edit(name: str, iftype: str, alias: Optional[str],
                               role: Optional[str], dedicated_to: Optional[str],
                               vrf: Optional[str]) -> Optional[str]:
    """
    Devuelve una etiqueta para clasificar una interface del backup destino.
    None = no reconocida (no es ni wan/mgmt/dmz/ha/lan ni modem ni logica conocida).

    T2: los metadatos explicitos (set role / set dedicated-to / set vrf /
    alias GESTION) priman sobre los prefijos de nombre.
    """
    n = name.lower()

    # 1. Metadata explicita (role-first) SOLO para fisicos: las logicas
    #    (switch/loopback/tunnel...) llevan `set role lan` en backups reales
    #    y deben seguir siendo logicas, no slots.
    if iftype == "physical":
        meta_kind = _explicit_metadata_class(role, dedicated_to, alias, vrf)
        if meta_kind is not None:
            return meta_kind

    # 2. Fallback por nombre (comportamiento previo)
    # WAN
    if n.startswith("wan"):
        return "wan"

    # HA
    if n in ("ha1", "ha2"):
        return "ha"

    # DMZ
    if n == "dmz":
        return "dmz"

    # MGMT
    if n == "mgmt":
        return "mgmt"

    # Modem
    if n == "modem":
        return "modem"

    # Logicas
    if iftype in {"tunnel", "aggregate", "vdom-link", "vlan", "switch"}:
        return "logical"

    # Port / internal / lan (LAN fisica). La familia FGT 30G / FortiWiFi 40F
    # nombra sus puertos LAN como lan1..lanN: deben reconocerse como slots.
    if iftype == "physical":
        if (n.startswith("port") or n.startswith("internal")
                or n.startswith("x") or n.startswith("lan")):
            return "lan"
        # Nombre fisico no canonico (ej. "a", "b", "fortilink")
        # Se conserva como logica para no perderlo en una migracion
        return "preserve_physical"

    return "ignore"


def extract_layout(template_text: str) -> DestinationLayout:
    """
    Parsea el texto del backup destino y devuelve el layout detectado.

    El resultado es un DestinationLayout (de interface_mapper) con la lista
    de slots en orden canonico y campos extra para preview:
      - model_hint: Optional[str]
      - lan_names: List[str] (nombres normalizados a portN)
      - logical_names: List[str]
      - modem_names: List[str]

    Lanza ValueError si el backup no tiene `config system interface`.
    """
    if not template_text or not template_text.strip():
        raise ValueError("El backup plantilla esta vacio")

    ast = parse(template_text)
    cfg = find_config(ast, "config system interface")
    if cfg is None:
        cfg = find_config(ast, "system interface")

    if cfg is None:
        raise ValueError(
            "El backup plantilla no contiene 'config system interface'"
        )

    info = _LegacyDestinationLayout(
        model_hint=detect_model(template_text),
        wan_count=0,
        has_mgmt=False,
        has_dmz=False,
        has_ha=False,
        lan_names=[],
        logical_names=[],
        modem_names=[],
    )

    wan_order: List[str] = []
    lan_order: List[str] = []
    seen_lan: set = set()
    # T1: nombres reales recolectados por clase especial (no literales)
    dmz_order: List[str] = []
    mgmt_order: List[str] = []
    ha_order: List[str] = []

    # Switches de hardware del destino (config system switch-interface):
    # nombre del switch -> miembros fisicos. En equipos como el FortiWiFi 40F
    # los puertos lan1/lan2 son miembros de un switch; el mapeador no debe
    # auto-llenarlos con interfaces ruteadas sin decision del usuario.
    switch_cfg = find_config(ast, "system switch-interface")
    switch_members: dict = {}
    if switch_cfg is not None:
        for edit in switch_cfg.children:
            if edit.kind != "edit":
                continue
            sw_name = edit.meta.get("name", "")
            if not sw_name:
                continue
            members = [
                m.strip().strip('"')
                for m in (get_set_value(edit, "member") or "").split()
                if m.strip()
            ]
            if members:
                switch_members[sw_name] = members

    for edit in cfg.children:
        if edit.kind != "edit":
            continue
        name = edit.meta.get("name", "")
        if not name:
            continue

        iftype = (get_set_value(edit, "type") or "").strip().strip('"')
        alias = get_set_value(edit, "alias")
        role = get_set_value(edit, "role")
        dedicated_to = get_set_value(edit, "dedicated-to")
        vrf = get_set_value(edit, "vrf")

        kind = _classify_destination_edit(name, iftype, alias, role, dedicated_to, vrf)
        if kind is None:
            continue

        if kind == "wan":
            info.wan_count += 1
            if name not in wan_order:
                wan_order.append(name)
        elif kind == "ha":
            info.has_ha = True
            if name not in ha_order:
                ha_order.append(name)
        elif kind == "dmz":
            info.has_dmz = True
            if name not in dmz_order:
                dmz_order.append(name)
        elif kind == "mgmt":
            info.has_mgmt = True
            if name not in mgmt_order:
                mgmt_order.append(name)
        elif kind == "lan":
            if name not in seen_lan:
                lan_order.append(name)
                seen_lan.add(name)
        elif kind == "logical":
            if name not in info.logical_names:
                info.logical_names.append(name)
        elif kind == "modem":
            if name not in info.modem_names:
                info.modem_names.append(name)
        elif kind == "preserve_physical":
            # T8: solo los nombres que empiezan por modem (case-insensitive)
            # pertenecen al bucket de modems; los demas fisicos no canonicos
            # se recogen en _misc_physicals para no confundir al consumidor.
            if re.match(r"^modem", name, re.IGNORECASE):
                if name not in info.modem_names:
                    info.modem_names.append(name)
            elif name not in info._misc_physicals:
                info._misc_physicals.append(name)

    # Los slots conservan el nombre real de la interfaz en el backup destino:
    # renombrar a wanN/portN normalizados crearia interfaces inexistentes.
    info.lan_names = list(lan_order)
    info.dmz_names = list(dmz_order)
    info.mgmt_names = list(mgmt_order)
    info.ha_names = list(ha_order)

    # Construir slots en orden canonico usando los NOMBRES REALES del backup
    # destino (dmz..., mgmt..., wan..., ha..., lan..., misc): regenerar
    # literales ('dmz', 'mgmt', 'ha1') crearia interfaces inexistentes.
    slots: List[str] = []
    slots.extend(dmz_order)
    slots.extend(mgmt_order)
    slots.extend(wan_order)
    slots.extend(ha_order)
    slots.extend(info.lan_names)
    slots.extend(info._misc_physicals)

    # Construir DestinationLayout final con campos extra
    layout = DestinationLayout(
        model_hint=info.model_hint,
        slots=slots,
        logical_names=info.logical_names,
        modem_names=info.modem_names,
        _misc_physicals=info._misc_physicals,
        switch_members=switch_members,
        dmz_names=info.dmz_names,
        mgmt_names=info.mgmt_names,
        ha_names=info.ha_names,
    )
    return layout


def summarize(layout: DestinationLayout) -> str:
    """Resumen legible del layout para mostrar en la GUI."""
    # Usar slots si esta disponible, sino fallback a campos legacy
    parts = []
    lan_count = len(layout.lan_names) if hasattr(layout, "lan_names") else layout.lan_count
    wan_count = layout.wan_count
    parts.append(f"{lan_count} puertos LAN")
    flags = []
    if layout.has_wan:
        flags.append(f"{wan_count} WAN")
    if layout.has_mgmt:
        flags.append("mgmt")
    if layout.has_dmz:
        flags.append("dmz")
    if layout.has_ha:
        flags.append("HA")
    if flags:
        parts.append(", ".join(flags))
    if hasattr(layout, "logical_names") and layout.logical_names:
        parts.append(f"+{len(layout.logical_names)} logicas")
    if hasattr(layout, "modem_names") and layout.modem_names:
        parts.append(f"+{len(layout.modem_names)} fisicas no canonicas")
    return " · ".join(parts)