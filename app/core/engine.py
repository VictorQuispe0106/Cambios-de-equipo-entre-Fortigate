"""
Orquestador principal: ejecuta el pipeline completo de migracion.

Flujo:
  1. parsear backup origen
  2. parsear backup destino (plantilla) -> DestinationLayout
  3. clasificar interfaces del origen
  4. detectar propuesta de reasignacion (si no se paso del usuario)
  5. mapear a layout destino (elimina snmp-index, conserva logicas)
  6. renombrar referencias en el resto del archivo
  7. inyectar usuario "claro" (opcional)
  8. serializar a texto
  9. validar output
  10. devolver texto + log + warnings + mapping + validacion
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .parser import parse, AST
from .writer import render
from .model_detector import detect_model
from .interface_classifier import classify
from .interface_mapper import (
    map_interfaces,
    apply_switch_member_fixups,
    DestinationLayout,
    DestinationProfile,
    MapperResult,
    Reassignment,
    detect_reassignments,
)
from .renamer import (
    rename_references,
    find_unrenamed_references,
    find_orphaned_references,
    get_interface_names_from_config,
)
from .admin_injector import inject_claro
from .template_parser import extract_layout as _extract_layout_raw, summarize as _summarize
from .config_validator import validate_config, ValidationResult


@dataclass
class EngineResult:
    output_text: str
    detected_model: Optional[str]
    layout: Optional[DestinationLayout]
    mapping: Dict[str, str]
    log: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    rename_counts: Dict[str, int] = field(default_factory=dict)
    claro_injected: bool = False
    reassignments: List[Reassignment] = field(default_factory=list)
    would_be_discarded: List[str] = field(default_factory=list)
    validation: Optional[ValidationResult] = None
    unrenamed_refs: List[Tuple[int, str, str]] = field(default_factory=list)
    orphaned_refs: List[Tuple[int, str, str]] = field(default_factory=list)


def run_pipeline(
    input_text: str,
    template_text: str,
    inject_admin: bool = True,
    reassignments: Optional[List[Reassignment]] = None,
    validate: bool = True,
) -> EngineResult:
    """
    Migra el backup origen al esquema del modelo destino usando la plantilla.

    Args:
        input_text: contenido del backup origen (modelo actual).
        template_text: contenido del backup destino (modelo al que se quiere pasar).
        inject_admin: si True, inyecta el usuario 'claro'.
        reassignments: lista de Reassignment del usuario (opcional).
        validate: si True, valida el output generado.

    Raises:
        ValueError: si la plantilla no es valida.
    """
    layout = _extract_layout_raw(template_text)
    ast = parse(input_text)
    detected = detect_model(input_text)
    classify(ast)

    # Si el usuario no especifico reasignaciones, calcular propuesta automatica
    actual_reassignments = reassignments
    if actual_reassignments is None:
        actual_reassignments, would_discard = _detect_reassign_for_layout(
            input_text, template_text, layout
        )
    else:
        _, would_discard = _detect_reassign_for_layout(input_text, template_text, layout)

    mapper_result = map_interfaces(ast, layout, reassignments=actual_reassignments)
    rename_counts = rename_references(ast, mapper_result.mapping)
    # Insertar set member de switches convertidos DESPUES del renombrado:
    # los miembros son puertos del destino y no deben reescribirse.
    apply_switch_member_fixups(mapper_result.switch_fixups)

    claro_injected = False
    if inject_admin:
        claro_injected = inject_claro(ast)

    output_text = render(ast)

    # Validacion del output
    validation_result = None
    unrenamed = []
    orphaned = []
    if validate:
        validation_result = validate_config(output_text)

        # Buscar referencias no renombradas
        unrenamed = find_unrenamed_references(output_text, mapper_result.mapping)
        if unrenamed:
            for line_no, iface, line_text in unrenamed:
                validation_result.warnings.append(
                    f"Linea {line_no}: referencia a '{iface}' no renombrada"
                )

        # Buscar interfaces huérfanas
        defined = get_interface_names_from_config(output_text)
        orphaned = find_orphaned_references(output_text, defined)
        if orphaned:
            for line_no, iface, line_text in orphaned:
                validation_result.warnings.append(
                    f"Linea {line_no}: interface '{iface}' referenciada pero no definida"
                )

        # Agregar warnings del mapper
        for w in mapper_result.warnings:
            validation_result.warnings.append(w)

        validation_result.is_valid = (
            len(validation_result.errors) == 0 and len(orphaned) == 0
        )

    return EngineResult(
        output_text=output_text,
        detected_model=detected,
        layout=layout,
        mapping=mapper_result.mapping,
        log=mapper_result.log,
        warnings=mapper_result.warnings,
        rename_counts=rename_counts,
        claro_injected=claro_injected,
        reassignments=mapper_result.reassignments,
        would_be_discarded=would_discard,
        validation=validation_result,
        unrenamed_refs=unrenamed,
        orphaned_refs=orphaned,
    )


def dry_run(
    input_text: str,
    template_text: str,
    inject_admin: bool = True,
    reassignments: Optional[List[Reassignment]] = None,
) -> EngineResult:
    """
    Simula el pipeline sin generar output final.
    Devuelve el mapping, warnings y validacion sin modificar el AST.
    """
    return run_pipeline(
        input_text, template_text,
        inject_admin=inject_admin,
        reassignments=reassignments,
        validate=True,
    )


def compute_diff_stats(original: str, modified: str) -> Dict[str, int]:
    """Computa estadisticas del diff entre original y modificado."""
    orig_lines = set(original.splitlines())
    mod_lines = set(modified.splitlines())

    added = mod_lines - orig_lines
    removed = orig_lines - mod_lines

    return {
        "original_lines": len(orig_lines),
        "modified_lines": len(mod_lines),
        "lines_added": len(added),
        "lines_removed": len(removed),
        "lines_changed": len(added) + len(removed),
    }


def _detect_reassign_for_layout(
    src_text: str, template_text: str, layout: DestinationLayout
) -> tuple:
    """Wrapper que detecta reasignaciones sin pasar por extract_layout dos veces."""
    return detect_reassignments(src_text, template_text)


def preview_reassignments(src_text: str, template_text: str) -> List[dict]:
    """
    Devuelve la propuesta de reasignacion como dicts (para JSON).
    Tambien devuelve los que serian descartados.
    """
    reassignments, discarded = detect_reassignments(src_text, template_text)
    return (
        [
            {
                "src_name": r.src_name,
                "src_kind": r.src_kind,
                "target_slot": r.target_slot,
                "original_role": r.original_role,
            }
            for r in reassignments
        ],
        discarded,
    )


def validate_balance(text: str) -> List[str]:
    issues: List[str] = []
    depth = 0
    line_no = 0
    for line in text.splitlines():
        line_no += 1
        stripped = line.strip()
        if stripped.startswith("config ") and not stripped.startswith("config-"):
            depth += 1
        elif stripped == "end":
            depth -= 1
            if depth < 0:
                issues.append(f"linea {line_no}: 'end' sin 'config' previo")
    if depth != 0:
        issues.append(f"desequilibrio: {depth} 'config' sin cerrar")
    return issues
