"""
Tests basicos para las mejoras del pipeline.
Valida: config_validator, renamer mejorado, dry-run, y compute_diff_stats.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

from core.config_validator import validate_config, format_validation_report
from core.renamer import (
    find_unrenamed_references,
    find_orphaned_references,
    get_interface_names_from_config,
)
from core.engine import compute_diff_stats


def test_validate_config_valid():
    config = """config system interface
    edit "port1"
        set mode static
    next
end
"""
    result = validate_config(config)
    assert result.is_valid, f"Expected valid, got errors: {result.errors}"
    print("PASS: test_validate_config_valid")


def test_validate_config_unbalanced():
    config = """config system interface
    edit "port1"
        set mode static
    next
"""
    result = validate_config(config)
    assert not result.is_valid, "Expected invalid due to missing end"
    assert any("sin cerrar" in e for e in result.errors), f"Expected unbalanced error, got: {result.errors}"
    print("PASS: test_validate_config_unbalanced")


def test_validate_config_duplicate_edit():
    config = """config system interface
    edit "port1"
        set mode static
    next
    edit "port1"
        set mode dhcp
    next
end
"""
    result = validate_config(config)
    # Duplicates are warnings, not errors
    assert len(result.warnings) > 0, "Expected warnings for duplicate edit"
    assert any("duplicado" in w.lower() for w in result.warnings), f"Expected duplicate warning, got: {result.warnings}"
    print("PASS: test_validate_config_duplicate_edit")


def test_validate_config_stats():
    config = """config system interface
    edit "port1"
        set mode static
        set ip 192.168.1.1 255.255.255.0
    next
end

config firewall policy
    edit 1
        set srcintf "port1"
        set dstintf "wan1"
    next
end
"""
    result = validate_config(config)
    assert result.stats["config_blocks"] == 2, f"Expected 2 config blocks, got {result.stats['config_blocks']}"
    assert result.stats["edit_blocks"] == 2, f"Expected 2 edit blocks, got {result.stats['edit_blocks']}"
    assert result.stats["set_commands"] == 4, f"Expected 4 set commands, got {result.stats['set_commands']}"
    print("PASS: test_validate_config_stats")


def test_find_unrenamed_references():
    text = """config system interface
    edit "wan1"
        set mode static
    next
end

config firewall policy
    edit 1
        set srcintf "internal1"
        set dstintf "wan1"
    next
end
"""
    mapping = {"internal1": "port1"}
    refs = find_unrenamed_references(text, mapping)
    assert len(refs) == 1, f"Expected 1 unrenamed ref, got {len(refs)}"
    assert refs[0][1] == "internal1", f"Expected internal1, got {refs[0][1]}"
    print("PASS: test_find_unrenamed_references")


def test_find_orphaned_references():
    text = """config system interface
    edit "port1"
        set mode static
    next
end

config firewall policy
    edit 1
        set srcintf "port1"
        set dstintf "wan1"
    next
end
"""
    defined = {"port1"}
    refs = find_orphaned_references(text, defined)
    assert len(refs) == 1, f"Expected 1 orphaned ref, got {len(refs)}"
    assert refs[0][1] == "wan1", f"Expected wan1, got {refs[0][1]}"
    print("PASS: test_find_orphaned_references")


def test_get_interface_names():
    text = """config system interface
    edit "port1"
        set mode static
    next
    edit "wan1"
        set mode dhcp
    next
    edit "internal1"
        set mode static
    next
end
"""
    names = get_interface_names_from_config(text)
    assert names == {"port1", "wan1", "internal1"}, f"Expected 3 interfaces, got {names}"
    print("PASS: test_get_interface_names")


def test_compute_diff_stats():
    original = "line1\nline2\nline3"
    modified = "line1\nline2_new\nline4"
    stats = compute_diff_stats(original, modified)
    assert stats["original_lines"] == 3, f"Expected 3 original lines, got {stats['original_lines']}"
    assert stats["modified_lines"] == 3, f"Expected 3 modified lines, got {stats['modified_lines']}"
    assert stats["lines_added"] == 2, f"Expected 2 added lines, got {stats['lines_added']}"
    assert stats["lines_removed"] == 2, f"Expected 2 removed lines, got {stats['lines_removed']}"
    print("PASS: test_compute_diff_stats")


def test_format_validation_report():
    config = """config system interface
    edit "port1"
        set mode static
    next
end
"""
    result = validate_config(config)
    report = format_validation_report(result)
    assert "válido" in report or "VALIDO" in report, f"Expected válido in report, got: {report[:100]}"
    print("PASS: test_format_validation_report")


if __name__ == "__main__":
    test_validate_config_valid()
    test_validate_config_unbalanced()
    test_validate_config_duplicate_edit()
    test_validate_config_stats()
    test_find_unrenamed_references()
    test_find_orphaned_references()
    test_get_interface_names()
    test_compute_diff_stats()
    test_format_validation_report()
    print("\nAll tests passed!")
