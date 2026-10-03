"""
Motor de mapeo de interfaces.

Dos modos de operacion:
  1. DestinationProfile (legacy): flags has_mgmt/has_dmz/has_ha + lan_ports numerico.
  2. DestinationLayout: lista explicita de slots detectada del backup plantilla.

El modo 2 es el canonico. El modo 1 se construye internamente a partir del 2
cuando solo se pasan flags + numerico.

Reasignacion de excedentes:
  Cuando el origen tiene interfaces que el destino no admite (WAN, dmz, HA),
  en lugar de descartarlas se reasignan a los primeros slots LAN vacios.
  El usuario puede sobreescribir la propuesta via 'reassignments' parameter.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Tuple

from .parser import Node, AST, find_config, get_set_value, remove_set
from .interface_classifier import InterfaceInfo, classify


# ============================================================
# Perfiles de destino
# ============================================================

@dataclass
class DestinationProfile:
    """Perfil numerico (modo legacy o derivado)."""
    model: str = ""
    has_mgmt: bool = False
    has_dmz: bool = False
    has_ha: bool = False
    lan_ports: int = 0
    wan_count: int = 2

    def to_layout(self) -> "DestinationLayout":
        slots: List[str] = []
        if self.has_dmz:
            slots.append("dmz")
        if self.has_mgmt:
            slots.append("mgmt")
        for i in range(1, self.wan_count + 1):
            slots.append(f"wan{i}")
        if self.has_ha:
            slots.append("ha1")
            slots.append("ha2")
        for i in range(1, self.lan_ports + 1):
            slots.append(f"port{i}")
        return DestinationLayout(
            model_hint=self.model or None,
            slots=slots,
        )


@dataclass
class DestinationLayout:
    """
    Layout explicito del destino: lista de nombres de slot en el orden canonico.
    Ejemplo: ['dmz', 'mgmt', 'wan1', 'wan2', 'ha1', 'ha2', 'port1', ..., 'port20']
    """
    model_hint: Optional[str] = None
    slots: List[str] = field(default_factory=list)
    logical_names: List[str] = field(default_factory=list)
    modem_names: List[str] = field(default_factory=list)
    # T8: fisicos no canonicos que NO son modem* (ej. fortilink, "a")
    _misc_physicals: List[str] = field(default_factory=list)

    @property
    def wan_count(self) -> int:
        return sum(1 for s in self.slots if s.lower().startswith("wan"))

    @property
    def has_wan(self) -> bool:
        return self.wan_count > 0

    @property
    def has_mgmt(self) -> bool:
        return any(s.lower() == "mgmt" for s in self.slots)

    @property
    def has_dmz(self) -> bool:
        return any(s.lower() == "dmz" for s in self.slots)

    @property
    def has_ha(self) -> bool:
        return any(s.lower() in ("ha1", "ha2") for s in self.slots)

    @property
    def lan_count(self) -> int:
        return sum(1 for s in self.slots if s.lower().startswith("port"))

    @property
    def lan_names(self) -> List[str]:
        return [s for s in self.slots if s.lower().startswith("port")]

    def has_slot(self, name: str) -> bool:
        n = name.lower()
        return any(s.lower() == n for s in self.slots)


# ============================================================
# Reasignacion
# ============================================================

@dataclass
class Reassignment:
    """
    Propuesta o decision del usuario sobre donde reasignar una interface
    del origen que no tiene slot nativo en el destino.

    Atributos:
      - src_name: nombre original en el backup origen (ej. "wan1", "dmz")
      - src_kind: tipo de la interface original ("wan", "dmz", "ha", "modem", "physical_other")
      - target_slot: slot destino donde reasignar (ej. "port5")
      - original_role: rol original de la interface (informativo)
    """
    src_name: str
    src_kind: str
    target_slot: str
    original_role: Optional[str] = None


@dataclass
class MapperResult:
    mapping: Dict[str, str] = field(default_factory=dict)
    log: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    reassignments: List[Reassignment] = field(default_factory=list)


# ============================================================
# Helpers
# ============================================================

def _strip_snmp_index(node: Node) -> None:
    remove_set(node, "snmp-index")


def _make_empty_interface(name: str, indent_text: str = "    ") -> Node:
    node = Node(
        kind="edit",
        text=f'{indent_text}edit "{name}"',
        meta={"name": name, "indent": indent_text},
    )
    node.add_child(Node(kind="set", text=f'{indent_text}    set vdom "root"'))
    node.add_child(Node(kind="set", text=f'{indent_text}    set type physical'))
    return node


def _clone_edit_renaming(node: Node, new_name: str) -> Node:
    old_text = node.text
    stripped = old_text.lstrip()
    indent = old_text[: len(old_text) - len(stripped)]
    new_text = f'{indent}edit "{new_name}"'
    new_node = Node(
        kind="edit",
        text=new_text,
        meta={**node.meta, "name": new_name},
    )
    for child in node.children:
        new_node.add_child(child)
    return new_node


def _priority_order(kind: str) -> int:
    """Prioridad para asignar slots vacios (menor = antes)."""
    order = {
        "wan": 0,
        "dmz": 1,
        "ha": 2,
        "mgmt": 3,
        "modem": 4,
        "physical_other": 5,
    }
    return order.get(kind, 99)

# ============================================================
# Deteccion de propuesta de reasignacion (antes de procesar)
# ============================================================

def detect_reassignments(src_text: str, template_text: str) -> Tuple[List[Reassignment], List[str]]:
    """
    Parsea el backup origen y la plantilla, devuelve:
      - Lista de TODOS los excedentes como Reassignment con suggested_slot
        (puede ser "" si no hay slot libre automatico; el usuario elegira manualmente).
      - Lista de slots disponibles automaticamente (informativo).

    El algoritmo:
      1. Calcula que interfaces caben nativamente en cada slot del destino.
      2. Identifica TODOS los excedentes (lo que quedo en pools).
      3. Para cada excedente, intenta asignarlo al primer slot LAN libre.
         Si no hay slot libre, suggested_slot queda vacio (el usuario elige manual).
      4. Orden de prioridad: wan, dmz, ha, mgmt, modem, lan_port.
    """
    from .template_parser import extract_layout
    from .parser import parse

    layout = extract_layout(template_text)
    ast = parse(src_text)
    classified = classify(ast)

    def _kind(info: InterfaceInfo) -> str:
        return info.node.meta.get("_class", "logical")

    # 1. Calcular que interfaces caben nativamente
    used_slots: Set[str] = set()
    pools_native: Dict[str, List[InterfaceInfo]] = {
        "wan": [], "mgmt": [], "dmz": [], "ha": [], "lan_port": [],
    }
    for info in classified:
        kind = _kind(info)
        if kind in pools_native:
            pools_native[kind].append(info)

    for slot in layout.slots:
        slot_l = slot.lower()
        if slot_l.startswith("wan") and pools_native["wan"]:
            pools_native["wan"].pop(0)
            used_slots.add(slot_l)
        elif slot_l in ("ha1", "ha2") and pools_native["ha"]:
            pools_native["ha"].pop(0)
            used_slots.add(slot_l)
        elif slot_l == "dmz" and pools_native["dmz"]:
            pools_native["dmz"].pop(0)
            used_slots.add(slot_l)
        elif slot_l == "mgmt" and pools_native["mgmt"]:
            pools_native["mgmt"].pop(0)
            used_slots.add(slot_l)
        elif slot_l.startswith("port") and pools_native["lan_port"]:
            pools_native["lan_port"].pop(0)
            used_slots.add(slot_l)

    # 2. Identificar TODOS los excedentes
    excedentes: List[Tuple[InterfaceInfo, str]] = []
    for kind in ["wan", "dmz", "ha", "mgmt", "lan_port"]:
        for info in pools_native[kind]:
            excedentes.append((info, kind))

    # Modem siempre es excedente
    for info in classified:
        if _kind(info) == "modem":
            excedentes.append((info, "modem"))

    # Ordenar por prioridad
    excedentes.sort(key=lambda pair: _priority_order(pair[1]))

    # 3. Asignar slots libres (los portN que quedaron sin consumir)
    available = [s for s in layout.lan_names if s not in used_slots]
    reassignments: List[Reassignment] = []
    discarded: List[str] = []

    for info, kind in excedentes:
        if available:
            suggested = available.pop(0)
            reassignments.append(Reassignment(
                src_name=info.name,
                src_kind=kind,
                target_slot=suggested,
                original_role=info.role,
            ))
        else:
            # Sin slot libre: sugerimos vacio, el usuario debe elegir manualmente
            reassignments.append(Reassignment(
                src_name=info.name,
                src_kind=kind,
                target_slot="",
                original_role=info.role,
            ))
            discarded.append(info.name)

    return reassignments, discarded


# ============================================================
# Mapper principal
# ============================================================

def map_interfaces(
    ast: AST,
    layout_or_profile,
    reassignments: Optional[List[Reassignment]] = None,
) -> MapperResult:
    """
    Reorganiza los nodos edit dentro de `config system interface` segun el layout
    destino (DestinationLayout o DestinationProfile).

    Si `reassignments` es None, calcula la propuesta automatica.
    Si viene del usuario, respeta sus elecciones.

    Algoritmo:
      1. Clasifica interfaces del origen en pools (wan, mgmt, dmz, ha, lan_port, modem, logical).
      2. Para cada slot del destino en orden:
         - Busca una interface del pool correspondiente.
         - Si encuentra, la clona renombrando al slot (y elimina snmp-index).
         - Si no, genera bloque vacio. Registra el slot como 'vacio disponible'.
      3. Las interfaces que sobran del pool:
         - Si hay reasignaciones definidas, las aplica.
         - Si no, calcula propuesta automatica y la aplica.
         - Si no quedan slots vacios, descarta con warning.
      4. Las interfaces logicas y modem (si quedan) se conservan al final.
    """
    if isinstance(layout_or_profile, DestinationLayout):
        layout = layout_or_profile
    elif isinstance(layout_or_profile, DestinationProfile):
        layout = layout_or_profile.to_layout()
    else:
        raise TypeError(f"Tipo no soportado: {type(layout_or_profile)}")

    cfg = find_config(ast, "system interface")
    if cfg is None:
        return MapperResult(warnings=["No se encontró 'config system interface'"])

    classified = classify(ast)

    def _kind(info: InterfaceInfo) -> str:
        return info.node.meta.get("_class", "logical")

    pools: Dict[str, List[InterfaceInfo]] = {
        "wan": [], "mgmt": [], "dmz": [], "ha": [],
        "lan_port": [], "modem": [], "logical": [],
    }
    for info in classified:
        kind = _kind(info)
        if kind in pools:
            pools[kind].append(info)

    result = MapperResult()
    new_children: List[Node] = []
    used_nodes: set = set()
    consumed_lan_slots: List[str] = []  # slots portN usados en el paso 2
    used_slots: Set[str] = set()  # nombres de slot ya generados

    # T3: conservar comentarios y lineas en blanco del bloque original.
    # Los previos al primer edit se emiten al inicio del bloque; los
    # desplazados entre edits se emiten al final en lugar de descartarse.
    prelude: List[Node] = []
    displaced_notes: List[Node] = []
    _leading = True
    for child in cfg.children:
        if child.kind in ("comment", "blank"):
            (prelude if _leading else displaced_notes).append(child)
            continue
        _leading = False

    # Slots objetivo de reasignaciones manuales: no llenar en Paso 2
    user_target_slots: Set[str] = set()
    user_source_names: Set[str] = set()
    if reassignments:
        for ra in reassignments:
            if ra.target_slot and ra.target_slot.strip():
                user_target_slots.add(ra.target_slot.strip().lower())
            if ra.src_name and ra.src_name.strip():
                user_source_names.add(ra.src_name.strip())

    def take_from(kind: str) -> Optional[InterfaceInfo]:
        for info in pools[kind]:
            if id(info.node) in used_nodes:
                continue
            # No consumir fuentes de reasignacion manual (se colocan en Paso 3)
            if info.name in user_source_names:
                continue
            # Nativas cuyo propio slot fue reservado para reasignacion manual:
            # quedan desplazadas (se descartan con warning en Paso 3)
            if info.name.lower() in user_target_slots:
                continue
            used_nodes.add(id(info.node))
            return info
        return None

    # Paso 2: poblar slots del destino en orden
    for slot in layout.slots:
        slot_l = slot.lower()
        used_slots.add(slot_l)

        if slot_l in user_target_slots:
            # Slot reservado para reasignacion manual (port, wan, dmz, mgmt,
            # ha, modem): dejar vacio para que Paso 3 lo llene en su posicion
            # canonica en lugar de anadirlo al final fuera de orden.
            new_children.append(_make_empty_interface(slot))
            result.log.append(f"{slot}: reservado para reasignacion manual")
            if slot_l.startswith("port"):
                consumed_lan_slots.append(slot)
            continue

        if slot_l.startswith("wan"):
            src = take_from("wan")
            if src:
                new = _clone_edit_renaming(src.node, slot)
                _strip_snmp_index(new)
                result.mapping[src.name] = slot
                result.log.append(f"{src.name} -> {slot}")
                new_children.append(new)
            else:
                new_children.append(_make_empty_interface(slot))
                result.log.append(f"{slot}: bloque vacío generado")
        elif slot_l in ("ha1", "ha2"):
            src = take_from("ha")
            if src:
                new = _clone_edit_renaming(src.node, slot)
                _strip_snmp_index(new)
                result.mapping[src.name] = slot
                result.log.append(f"{src.name} -> {slot}")
                new_children.append(new)
            else:
                new_children.append(_make_empty_interface(slot))
                result.log.append(f"{slot}: bloque vacío generado")
        elif slot_l == "dmz":
            src = take_from("dmz")
            if src:
                new = _clone_edit_renaming(src.node, "dmz")
                _strip_snmp_index(new)
                result.mapping[src.name] = "dmz"
                result.log.append(f"{src.name} -> dmz")
                new_children.append(new)
            else:
                new_children.append(_make_empty_interface("dmz"))
                result.log.append("dmz: bloque vacío generado")
        elif slot_l == "mgmt":
            src = take_from("mgmt")
            if src:
                new = _clone_edit_renaming(src.node, "mgmt")
                _strip_snmp_index(new)
                result.mapping[src.name] = "mgmt"
                result.log.append(f"{src.name} -> mgmt")
                new_children.append(new)
            else:
                new_children.append(_make_empty_interface("mgmt"))
                result.log.append("mgmt: bloque vacío generado")
        elif slot_l.startswith("port"):
            # Alineacion canonica: el origen con el mismo nombre del slot es su
            # ocupante natural. Si es fuente de reasignacion manual (o quedo
            # desplazado por un slot reservado), el slot queda vacio.
            src = None
            identity = next(
                (i for i in pools["lan_port"]
                 if id(i.node) not in used_nodes and i.name.lower() == slot_l),
                None,
            )
            if identity is not None:
                if identity.name not in user_source_names and identity.name.lower() not in user_target_slots:
                    src = identity
            else:
                for info in pools["lan_port"]:
                    if id(info.node) in used_nodes:
                        continue
                    if info.name in user_source_names or info.name.lower() in user_target_slots:
                        src = None
                        break
                    src = info
                    break
            if src is not None:
                used_nodes.add(id(src.node))
                new = _clone_edit_renaming(src.node, slot)
                _strip_snmp_index(new)
                result.mapping[src.name] = slot
                result.log.append(f"{src.name} -> {slot}")
                new_children.append(new)
                consumed_lan_slots.append(slot)
            else:
                # Recordar como slot vacio disponible para reasignacion
                new_children.append(_make_empty_interface(slot))
                result.log.append(f"{slot}: bloque vacío generado")
                consumed_lan_slots.append(slot)

    # Paso 3: procesar excedentes (lo que quedo en los pools)
    # Calcular slots LAN disponibles (los que se generaron como vacios)
    available_lan_slots = [
        s for s in consumed_lan_slots
        if any(c.meta.get("name") == s and len(c.children) == 2  # solo los vacios (vdom + type)
               for c in new_children)
    ]
    # Fallback mas robusto: un slot esta disponible si NO tiene un mapping que le apunte
    mapped_targets = set(result.mapping.values())
    available_lan_slots = [
        s for s in layout.lan_names
        if s not in mapped_targets
    ]

    # Construir lista de excedentes
    excedentes: List[Tuple[InterfaceInfo, str]] = []
    for kind in ["wan", "dmz", "ha", "mgmt", "modem", "lan_port"]:
        for info in pools[kind]:
            if id(info.node) not in used_nodes:
                excedentes.append((info, kind))
    excedentes.sort(key=lambda pair: _priority_order(pair[1]))

    # Aplicar reasignaciones (automaticas o del usuario)
    reassignment_map: Dict[str, str] = {}  # src_name -> target_slot
    if reassignments is not None:
        # Validar que el usuario no asigne dos interfaces al mismo slot
        used_targets: Set[str] = set()
        for ra in reassignments:
            target = ra.target_slot
            if target in used_targets:
                result.warnings.append(
                    f"Reasignacion duplicada al slot '{target}': solo se aplicara la primera"
                )
                continue
            used_targets.add(target)
            reassignment_map[ra.src_name] = target
    else:
        # Automatico: asignar excedentes en orden a slots disponibles
        for info, kind in excedentes:
            if available_lan_slots:
                target = available_lan_slots.pop(0)
                reassignment_map[info.name] = target

    # Aplicar reasignaciones
    reassigned_objs: List[Reassignment] = []
    for info, kind in excedentes:
        src_name = info.name
        if src_name not in reassignment_map:
            # No hay slot (no vino en reassignments explicitos), descartar.
            # Si su propio slot fue reservado para una reasignacion manual,
            # la interface nativa fue desplazada: avisar con el motivo.
            reason = ""
            if src_name.lower() in user_target_slots:
                reason = f"reemplazada por reasignacion manual a '{src_name}'"
            _emit_discard_warning(result, info, kind, layout, reason)
            continue
        target_slot = reassignment_map[src_name]

        # Si el usuario no eligio slot (dropdown vacio), descartar
        if not target_slot or target_slot.strip() == "":
            _emit_discard_warning(result, info, kind, layout)
            continue

        # Quitar el bloque (vacio o nativo) que habiamos puesto para target_slot
        # y reemplazarlo con la interface renombrada.
        replaced = False
        for i, c in enumerate(new_children):
            if c.meta.get("name") == target_slot:
                # Verificar si era una asignacion nativa: buscar el origen
                native_origin = None
                for orig_name, target in list(result.mapping.items()):
                    if target == target_slot and orig_name != src_name:
                        native_origin = orig_name
                        break
                if native_origin:
                    # La interface nativa debe volver al pool para posible reasignacion posterior
                    del result.mapping[native_origin]
                    _warn_displaced_native(result, pools, native_origin, layout, target_slot)
                # Reemplazar el bloque (sea vacio o nativo)
                new = _clone_edit_renaming(info.node, target_slot)
                _strip_snmp_index(new)
                new_children[i] = new
                replaced = True
                break
        if not replaced:
            new = _clone_edit_renaming(info.node, target_slot)
            _strip_snmp_index(new)
            new_children.append(new)
        result.mapping[src_name] = target_slot
        original = _get_role_description(info)
        result.log.append(
            f"{src_name} -> {target_slot} (reasignado: {original} sin slot nativo en destino)"
        )
        used_nodes.add(id(info.node))
        reassigned_objs.append(Reassignment(
            src_name=src_name,
            src_kind=kind,
            target_slot=target_slot,
            original_role=info.role,
        ))

    result.reassignments = reassigned_objs

    # Paso 4: logicas y modem restantes se conservan al final
    for m in pools["modem"]:
        if id(m.node) in used_nodes:
            continue
        if m.is_physical:
            new = _clone_edit_renaming(m.node, m.name)
            _strip_snmp_index(new)
            new_children.append(new)
        else:
            new_children.append(m.node)
        result.log.append(f"{m.name} (modem) -> conservada")

    for l in pools["logical"]:
        # T4: subinterfaces fisicas (ej. port1.100) renombran junto con su padre
        name = l.name
        if "." in name:
            parent, suffix = name.split(".", 1)
            new_parent = result.mapping.get(parent)
            if new_parent and new_parent != parent:
                renamed = f"{new_parent}.{suffix}"
                new = _clone_edit_renaming(l.node, renamed)
                _strip_snmp_index(new)
                new_children.append(new)
                result.log.append(f"{name} -> {renamed} (subinterface, padre renombrado)")
                continue
        new_children.append(l.node)
        result.log.append(f"{l.name} (logical {l.iftype}) -> conservada")

    cfg.children = prelude + new_children + displaced_notes
    return result


def _get_role_description(info: InterfaceInfo) -> str:
    """Descripcion legible del rol original de una interface."""
    n = info.name.lower()
    if n.startswith("wan"):
        return f"WAN ({info.name})"
    if n == "dmz":
        return "DMZ"
    if n in ("ha1", "ha2"):
        return f"HA ({info.name})"
    if n == "modem":
        return "modem"
    return f"puerto fisico ({info.name})"


def _warn_displaced_native(
    result: MapperResult,
    pools: Dict[str, List[InterfaceInfo]],
    native_origin: str,
    layout: DestinationLayout,
    target_slot: str,
) -> None:
    """Emite un warning cuando una reasignacion manual desplaza una interface
    nativa que ya fue consumida en Paso 2 (su bloque ya no se emite)."""
    displaced = None
    for infos in pools.values():
        for info in infos:
            if info.name == native_origin:
                displaced = info
                break
        if displaced is not None:
            break
    reason = f"reemplazada por reasignacion manual a '{target_slot}'"
    if displaced is not None:
        _emit_discard_warning(result, displaced, displaced.node.meta.get("_class", "logical"), layout, reason)
    else:
        result.warnings.append(
            f"interfaz '{native_origin}' desplazada: su bloque '{target_slot}' fue "
            f"{reason} y ya no se emite en el output"
        )


def _emit_discard_warning(result: MapperResult, info: InterfaceInfo, kind: str, layout: DestinationLayout, reason: str = "") -> None:
    """Emite un warning legible para una interface descartada."""
    reason_suffix = f" ({reason})" if reason else ""
    if kind == "wan":
        result.warnings.append(
            f"WAN '{info.name}' descartada: destino sin slots WAN disponibles para reasignar{reason_suffix}"
        )
    elif kind == "dmz":
        result.warnings.append(f"dmz '{info.name}' descartada: sin slot dmz ni LAN libre{reason_suffix}")
    elif kind == "ha":
        result.warnings.append(f"ha '{info.name}' descartada: sin slots HA ni LAN libre{reason_suffix}")
    elif kind == "mgmt":
        result.warnings.append(f"mgmt '{info.name}' descartada: sin slot mgmt ni LAN libre{reason_suffix}")
    elif kind == "modem":
        result.warnings.append(f"modem '{info.name}' descartado: sin LAN libre{reason_suffix}")
    elif kind == "lan_port":
        result.warnings.append(
            f"puerto fisico '{info.name}' descartado: destino solo admite {layout.lan_count} puertos LAN y todos estan ocupados{reason_suffix}"
        )
    else:
        result.warnings.append(f"interfaz '{info.name}' descartada (sin slot disponible){reason_suffix}")