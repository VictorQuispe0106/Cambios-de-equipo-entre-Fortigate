"""Modulo __init__ del paquete core."""

from .parser import parse, find_config, AST, Node, get_set_value, remove_set
from .writer import render
from .model_detector import detect_model
from .interface_classifier import classify, InterfaceInfo
from .interface_mapper import (
    map_interfaces,
    DestinationProfile,
    DestinationLayout,
    MapperResult,
    Reassignment,
    detect_reassignments,
)
from .renamer import rename_references
from .admin_injector import inject_claro
from .template_parser import extract_layout, summarize as _summarize
from .engine import run_pipeline, validate_balance, EngineResult, preview_reassignments

__all__ = [
    "parse",
    "find_config",
    "AST",
    "Node",
    "get_set_value",
    "remove_set",
    "render",
    "detect_model",
    "classify",
    "InterfaceInfo",
    "map_interfaces",
    "DestinationProfile",
    "DestinationLayout",
    "MapperResult",
    "Reassignment",
    "detect_reassignments",
    "rename_references",
    "inject_claro",
    "extract_layout",
    "run_pipeline",
    "validate_balance",
    "EngineResult",
    "preview_reassignments",
]