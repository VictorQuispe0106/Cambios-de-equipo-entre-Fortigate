"""Casos borde del camino de excedentes y del scanner de referencias.

Cubre los defectos encontrados verificando migraciones reales
(100F->80F / 100F->60F): dedup de reasignaciones con target vacio,
macros/wildcards falsos positivos, y vdom-formato 'any'.
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.renamer import find_orphaned_references  # noqa: E402


MINIMAL_CONF = """
config system interface
    edit "wan1"
        set vdom "root"
        set type physical
    next
    edit "port1"
        set vdom "root"
        set type physical
    next
end
config system admin
    edit "admin"
        set accprofile "super_admin"
    next
end
"""

LAYOUT_80F = """
config system interface
    edit "wan1"
        set type physical
    next
    edit "dmz"
        set type physical
    next
    edit "internal1"
        set alias "LAN"
        set type physical
    next
    edit "a"
        set role lan
        set type physical
    next
    edit "modem"
        set type modem
    next
end
"""


class BlankTargetDedup(unittest.TestCase):
    def test_blank_targets_are_silent_not_duplicates(self):
        """Target vacio significa 'sin eleccion manual': NO debe generar
        warnings de duplicados ni entrar al mapa (se descarta despues)."""
        from core.interface_mapper import map_interfaces, _make_empty_interface  # noqa
        from core.template_parser import extract_layout
        from core.parser import parse
        from core.interface_classifier import classify
        from core.interface_mapper import Reassignment

        ast = parse(MINIMAL_CONF)
        classify(ast)
        layout = extract_layout(LAYOUT_80F)
        # Dos reasignaciones con target vacio (caso tipico del server)
        ras = [
            Reassignment(src_name="port1", src_kind="lan_port", target_slot=""),
            Reassignment(src_name="port1", src_kind="lan_port", target_slot=""),
        ]
        result = map_interfaces(ast, layout, reassignments=ras)
        dups = [w for w in result.warnings if "duplicada" in w.lower()]
        self.assertEqual([], dups, f"falsos duplicados con target vacio: {dups}")

    def test_duplicate_real_targets_warn_once(self):
        """Dos interfaces al mismo slot REAL: un warning, primera gana."""
        from core.interface_mapper import map_interfaces
        from core.template_parser import extract_layout
        from core.parser import parse
        from core.interface_classifier import classify
        from core.interface_mapper import Reassignment

        ast = parse(MINIMAL_CONF)
        classify(ast)
        layout = extract_layout(LAYOUT_80F)
        ras = [
            Reassignment(src_name="port1", src_kind="lan_port", target_slot="dmz"),
            Reassignment(src_name="port1", src_kind="lan_port", target_slot="dmz"),
        ]
        result = map_interfaces(ast, layout, reassignments=ras)
        dups = [w for w in result.warnings if "duplicada" in w.lower()]
        self.assertEqual(1, len(dups))


class IgnoreNoninterfaceValues(unittest.TestCase):
    def test_orphan_scan_ignores_any_wildcard_macros(self):
        text = (
            'config system dhcp server\n'
            '    set interface "any"\n'
            'next\n'
            'end\n'
            'config firewall policy\n'
            '    edit 1\n'
            '        set dstintf "*"\n'
            '        set srcintf "$(VDOM_LINKS)"\n'
            '    next\n'
            'end\n'
        )
        defined = {"wan1", "port1"}
        orphans = find_orphaned_references(text, defined)
        self.assertEqual([], orphans, f"falsos positivos: {orphans}")

    def test_orphan_scan_still_catches_real_missing(self):
        text = (
            'config firewall policy\n'
            '    edit 1\n'
            '        set dstintf "port9"\n'
            '    next\n'
            'end\n'
        )
        orphans = find_orphaned_references(text, {"wan1"})
        self.assertEqual(1, len(orphans))


if __name__ == "__main__":
    unittest.main()
