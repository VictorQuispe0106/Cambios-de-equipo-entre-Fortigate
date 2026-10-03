"""
Validador de output FortiGate.

Verifica que el .conf generado sea sintácticamente válido y no tenga
problemas que puedan romper un equipo en producción.

Checks:
  1. Balance config/end
  2. Balance edit/next
  3. Interfaces huérfanas (referenciadas pero no definidas)
  4. Reglas con interfaces inexistentes
  5. Configuraciones incompletas
  6. Duplicados de edit dentro de un mismo config
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional


@dataclass
class ValidationResult:
    """Resultado de la validación del output."""
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)


def validate_config(text: str) -> ValidationResult:
    """
    Valida un archivo .conf de FortiGate y devuelve un resultado detallado.
    
    Args:
        text: Contenido del .conf a validar
        
    Returns:
        ValidationResult con errores, warnings y estadísticas
    """
    result = ValidationResult()
    lines = text.splitlines()
    
    # 1. Balance config/end
    _check_config_end_balance(lines, result)
    
    # 2. Balance edit/next
    _check_edit_next_balance(lines, result)
    
    # 3. Duplicados de edit
    _check_duplicate_edits(lines, result)
    
    # 4. Interfaces definidas vs referenciadas
    _check_interface_references(lines, result)
    
    # 5. Configuraciones incompletas
    _check_incomplete_configs(lines, result)
    
    # 6. Estadísticas básicas
    _compute_stats(lines, result)
    
    # Determinar validez final
    result.is_valid = len(result.errors) == 0
    
    return result


def _check_config_end_balance(lines: List[str], result: ValidationResult):
    """Verifica que cada 'config' tenga su 'end' correspondiente."""
    depth = 0
    line_no = 0
    config_stack = []
    
    for line in lines:
        line_no += 1
        stripped = line.strip()
        
        if stripped.startswith("config ") and not stripped.startswith("config-"):
            depth += 1
            config_stack.append(line_no)
        elif stripped == "end":
            depth -= 1
            if depth < 0:
                result.errors.append(
                    f"Línea {line_no}: 'end' sin 'config' previo (profundidad: {depth})"
                )
            elif config_stack:
                config_stack.pop()
    
    if depth > 0:
        result.errors.append(
            f"Desbalance: {depth} bloques 'config' sin cerrar (líneas: {config_stack})"
        )
    elif depth < 0:
        result.errors.append(
            f"Desbalance: {abs(depth)} bloques 'end' sin 'config' previo"
        )


def _check_edit_next_balance(lines: List[str], result: ValidationResult):
    """Verifica que cada 'edit' tenga su 'next' correspondiente."""
    depth = 0
    line_no = 0
    edit_stack = []
    
    for line in lines:
        line_no += 1
        stripped = line.strip()
        
        if stripped.startswith("edit ") and not stripped.startswith("editor"):
            depth += 1
            edit_stack.append(line_no)
        elif stripped.startswith("next"):
            depth -= 1
            if depth < 0:
                result.errors.append(
                    f"Línea {line_no}: 'next' sin 'edit' previo"
                )
            elif edit_stack:
                edit_stack.pop()
    
    if depth > 0:
        result.errors.append(
            f"Desbalance: {depth} bloques 'edit' sin cerrar (líneas: {edit_stack})"
        )
    elif depth < 0:
        result.errors.append(
            f"Desbalance: {abs(depth)} bloques 'next' sin 'edit' previo"
        )


def _check_duplicate_edits(lines: List[str], result: ValidationResult):
    """Detecta edits duplicados dentro del mismo bloque config."""
    config_stack = []
    edits_in_config: Dict[str, List[int]] = {}
    line_no = 0
    
    for line in lines:
        line_no += 1
        stripped = line.strip()
        
        if stripped.startswith("config ") and not stripped.startswith("config-"):
            config_name = stripped[len("config "):].strip()
            config_stack.append(config_name)
            edits_in_config = {}
        elif stripped == "end":
            if config_stack:
                config_stack.pop()
            edits_in_config = {}
        elif stripped.startswith("edit ") and not stripped.startswith("editor"):
            edit_name = stripped[len("edit "):].strip().strip('"')
            key = f"{'/'.join(config_stack)}/{edit_name}"
            if key in edits_in_config:
                result.warnings.append(
                    f"Línea {line_no}: edit '{edit_name}' duplicado en config '{'/'.join(config_stack)}'"
                )
            else:
                edits_in_config[key] = [line_no]


def _check_interface_references(lines: List[str], result: ValidationResult):
    """Verifica que las interfaces referenciadas existan."""
    # Interfaces definidas en config system interface
    defined_interfaces = set()
    in_interface_config = False
    
    for line in lines:
        stripped = line.strip()
        
        if stripped == "config system interface":
            in_interface_config = True
            continue
        elif stripped == "end" and in_interface_config:
            in_interface_config = False
            continue
        
        if in_interface_config and stripped.startswith("edit "):
            name = stripped[len("edit "):].strip().strip('"')
            defined_interfaces.add(name)
    
    if not defined_interfaces:
        result.warnings.append("No se encontraron interfaces en 'config system interface'")
        return
    
    # Interfaces referenciadas solo en firewall policy y router static
    # (no en firewall service, address, o address-group)
    referenced_interfaces = set()
    line_no = 0
    in_policy_config = False
    in_service_config = False
    in_address_config = False
    in_address_group_config = False
    
    for line in lines:
        line_no += 1
        stripped = line.strip()
        
        if stripped.startswith("config "):
            if "firewall policy" in stripped:
                in_policy_config = True
            elif "router static" in stripped:
                in_policy_config = True
            elif "firewall service" in stripped:
                in_service_config = True
            elif "firewall address " in stripped:
                in_address_config = True
            elif "firewall addrgrp" in stripped:
                in_address_group_config = True
        elif stripped == "end":
            in_policy_config = False
            in_service_config = False
            in_address_config = False
            in_address_group_config = False
        
        # Only check interface references in policy/routing contexts
        if not in_policy_config:
            continue
            
        if not stripped.startswith("set "):
            continue
        
        parts = stripped[4:].split(None, 1)
        if len(parts) < 2:
            continue
        
        key = parts[0]
        value = parts[1].strip()
        
        # Keys que referencian interfaces (solo en contexto de policy/routing)
        if key in ("srcintf", "dstintf", "interface", "extintf"):
            refs = re.findall(r'"([^"]+)"', value)
            if not refs:
                refs = [value.split()[0]] if value else []
            
            for ref in refs:
                if ref not in defined_interfaces:
                    referenced_interfaces.add(ref)
    
    if referenced_interfaces:
        for iface in sorted(referenced_interfaces):
            result.warnings.append(
                f"Interface '{iface}' referenciada pero no definida en 'config system interface'"
            )


def _check_incomplete_configs(lines: List[str], result: ValidationResult):
    """Detecta configs vacíos o con configuración incompleta."""
    line_no = 0
    config_start = 0
    config_name = ""
    has_content = False
    
    # Configs que normalmente están vacíos en FortiGate
    KNOWN_EMPTY_CONFIGS = {
        "system replacemsg",
        "redistribute",
        "redistribute6",
        "router multicast",
        "webfilter ips-urlfilter-setting",
        "vpn certificate ca",
        "casb saas-application",
        "casb user-activity",
        "system sso-admin",
        "firewall internet-service-definition",
        "cluster-peer",
        "sip",
        "imap",
        "pop3",
        "smtp",
        "main-class",
    }
    
    for line in lines:
        line_no += 1
        stripped = line.strip()
        
        if stripped.startswith("config ") and not stripped.startswith("config-"):
            config_start = line_no
            config_name = stripped[len("config "):].strip()
            has_content = False
        elif stripped == "end":
            if config_start > 0 and not has_content:
                # Skip known empty configs (check if config_name contains any known pattern)
                is_known_empty = any(
                    k in config_name.lower() for k in KNOWN_EMPTY_CONFIGS
                )
                if not is_known_empty:
                    result.warnings.append(
                        f"Línea {config_start}: config '{config_name}' vacío"
                    )
            config_start = 0
        elif stripped and not stripped.startswith("#"):
            has_content = True


def _compute_stats(lines: List[str], result: ValidationResult):
    """Calcula estadísticas básicas del config."""
    stats = {
        "total_lines": len(lines),
        "config_blocks": 0,
        "edit_blocks": 0,
        "set_commands": 0,
        "interfaces": 0,
        "policies": 0,
        "routes": 0,
    }
    
    in_interface_config = False
    in_policy_config = False
    in_route_config = False
    
    for line in lines:
        stripped = line.strip()
        
        if stripped.startswith("config ") and not stripped.startswith("config-"):
            stats["config_blocks"] += 1
            if "system interface" in stripped:
                in_interface_config = True
            elif "firewall policy" in stripped:
                in_policy_config = True
            elif "router static" in stripped:
                in_route_config = True
        elif stripped == "end":
            in_interface_config = False
            in_policy_config = False
            in_route_config = False
        elif stripped.startswith("edit "):
            stats["edit_blocks"] += 1
            if in_interface_config:
                stats["interfaces"] += 1
            elif in_policy_config:
                stats["policies"] += 1
        elif stripped.startswith("set "):
            stats["set_commands"] += 1
    
    result.stats = stats


def format_validation_report(result: ValidationResult) -> str:
    """Formatea el resultado de validación como texto legible."""
    lines = []
    
    if result.is_valid:
        lines.append("✅ Config válido")
    else:
        lines.append("❌ Config inválido")
    
    if result.errors:
        lines.append(f"\n🔴 Errores ({len(result.errors)}):")
        for error in result.errors:
            lines.append(f"  • {error}")
    
    if result.warnings:
        lines.append(f"\n🟡 Warnings ({len(result.warnings)}):")
        for warning in result.warnings:
            lines.append(f"  • {warning}")
    
    if result.stats:
        lines.append(f"\n📊 Estadísticas:")
        lines.append(f"  • Líneas totales: {result.stats.get('total_lines', 0)}")
        lines.append(f"  • Bloques config: {result.stats.get('config_blocks', 0)}")
        lines.append(f"  • Bloques edit: {result.stats.get('edit_blocks', 0)}")
        lines.append(f"  • Comandos set: {result.stats.get('set_commands', 0)}")
        lines.append(f"  • Interfaces: {result.stats.get('interfaces', 0)}")
        lines.append(f"  • Políticas: {result.stats.get('policies', 0)}")
    
    return "\n".join(lines)