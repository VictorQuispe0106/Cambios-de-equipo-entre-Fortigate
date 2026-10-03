"""Tests unitarios para renamer (single-pass) y comportamiento del mapper."""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.parser import parse, find_config
from core.renamer import rename_references, find_unrenamed_references
from core.writer import render


def _iface_edit(name, lines=None, indent="    "):
    out = [f'{indent}edit "{name}"', f'{indent}    set vdom "root"',
           f'{indent}    set type physical']
    for ln in (lines or []):
        out.append(f'{indent}    {ln}')
    out.append(f'{indent}next')
    return out


def _conf_iface(edit_lines):
    return "\n".join(
        ["#config-version=FGTTEST-7.4.12-FW-build2902-260505",
         "config system interface"] + edit_lines + ["end"]
    ) + "\n"


def _conf_ref_block(key, value):
    return "\n".join(
        ["config firewall policy",
         '    edit "1"',
         f'        set {key} {value}',
         "    next",
         "end"]
    ) + "\n"


class TestT1SinglePassRename(unittest.TestCase):
    """T1: mapeos encadenados no deben corromperse por re-escaneo secuencial."""

    def _build_ast(self):
        # Simula el estado post-mapper: los edits de config system interface
        # ya tienen nombres de slot destino (wan3->port4, port4->port5).
        conf = _conf_iface(_iface_edit("port4") + _iface_edit("port5"))
        conf += _conf_ref_block("dstintf", '"wan3"')
        conf += _conf_ref_block("dstintf", '"port4"')
        return parse(conf)

    def test_chained_mapping_not_corrupted(self):
        """wan3->port4 y port4->port5: refs a wan3 deben quedar en port4,
        refs a port4 deben ir a port5, en UN solo pase."""
        ast = self._build_ast()
        mapping = {"wan3": "port4", "port4": "port5"}
        counts = rename_references(ast, mapping)
        out = render(ast)
        self.assertIn('set dstintf "port4"', out,
                      "ref a wan3 debe renombrar a port4 y no ser rescaneada a port5")
        self.assertIn('set dstintf "port5"', out,
                      "ref a port4 debe renombrar a port5")
        self.assertNotIn('set dstintf "wan3"', out)
        self.assertEqual(counts.get("wan3"), 1)
        self.assertEqual(counts.get("port4"), 1)

    def test_unrenamed_no_false_positive_on_chained_values(self):
        """Tras el single pass, port4 en el output es producto del renombrado
        (valor del mapping), no una referencia no renombrada."""
        ast = self._build_ast()
        mapping = {"wan3": "port4", "port4": "port5"}
        rename_references(ast, mapping)
        out = render(ast)
        unrenamed = find_unrenamed_references(out, mapping)
        flagged = {name for _, name, _ in unrenamed}
        self.assertEqual(flagged, set(),
                         "no debe haber falsos positivos en mapping encadenado")


class TestT2ManualReassignDisplacement(unittest.TestCase):
    """T2: al sobrescribir un slot nativo con una reasignacion manual, la
    interface desplazada debe emitir un warning y el mapping debe quedar
    consistente con los bloques emitidos."""

    def test_manual_reassign_to_native_slot_warns_about_displaced(self):
        from core.interface_mapper import map_interfaces, DestinationLayout, Reassignment
        src = _conf_iface(
            _iface_edit("wan1") + _iface_edit("wan2") + _iface_edit("dmz", lines=["set role dmz"])
            + _iface_edit("port1")
        )
        ast = parse(src)
        layout = DestinationLayout(slots=["wan1", "wan2", "port1", "port2"])
        manual = [Reassignment(src_name="dmz", src_kind="dmz", target_slot="wan1")]
        result = map_interfaces(ast, layout, reassignments=manual)
        # mapping consistente: dmz ocupa wan1; wan2 y port1 siguen mapeados
        self.assertEqual(result.mapping.get("dmz"), "wan1")
        self.assertEqual(result.mapping.get("wan2"), "wan2")
        self.assertNotIn("wan1", result.mapping)
        # la interface nativa desplazada (wan1) debe avisar con el motivo
        warns = " ".join(result.warnings)
        self.assertIn("wan1", warns)
        self.assertIn("reasignacion manual", warns)


class TestT5ManualTargetCanonicalPosition(unittest.TestCase):
    """T5: reasignaciones manuales a slots wan/dmz/mgmt/ha/modem deben quedar
    pre-reservados en su posicion canonica (no solo los portN)."""

    def test_manual_map_to_mgmt_lands_in_canonical_position(self):
        from core.interface_mapper import map_interfaces, DestinationLayout, Reassignment
        src = _conf_iface(
            _iface_edit("mgmt", lines=["set dedicated-to management"])
            + _iface_edit("port1", lines=["set alias \"P1\""])
            + _iface_edit("port2")
        )
        ast = parse(src)
        layout = DestinationLayout(slots=["wan1", "wan2", "mgmt", "port1", "port2"])
        manual = [Reassignment(src_name="port1", src_kind="lan_port", target_slot="mgmt")]
        result = map_interfaces(ast, layout, reassignments=manual)
        # el mapa manual debe aplicarse: port1 -> mgmt en posicion canonica
        self.assertEqual(result.mapping.get("port1"), "mgmt",
                         "la reasignacion manual a un slot no-port no debe ignorarse")
        # sin append fuera de orden: exactamente los slots del layout, en orden
        cfg = find_config(ast, "system interface")
        names = [c.meta.get("name") for c in cfg.children if c.kind == "edit"]
        self.assertEqual(names, ["wan1", "wan2", "mgmt", "port1", "port2"])
        # el edit en la posicion mgmt debe contener el contenido de port1
        mgmt_edit = next(c for c in cfg.children if c.kind == "edit" and c.meta.get("name") == "mgmt")
        texts = "\n".join(ch.text for ch in mgmt_edit.children)
        self.assertIn('set alias "P1"', texts)
        # la nativa desplazada (mgmt) debe avisar
        warns = " ".join(result.warnings)
        self.assertIn("reasignacion manual", warns)


class TestT3CommentPreservation(unittest.TestCase):
    """T3: reconstruir cfg.children de config system interface no debe
    descartar comentarios/lineas en blanco del bloque."""

    def test_comments_and_blanks_preserved_in_interface_block(self):
        from core.interface_mapper import map_interfaces, DestinationLayout
        lines = [
            "#config-version=FGTTEST-7.4.12-FW-build2902-260505",
            "config system interface",
            "    # comentario inicial",
            "",
            '    edit "wan1"',
            '        set vdom "root"',
            '        set type physical',
            "    next",
            "    # comentario entre edits",
            '    edit "port1"',
            '        set vdom "root"',
            '        set type physical',
            "    next",
            "end",
        ]
        src = "\n".join(lines) + "\n"
        ast = parse(src)
        layout = DestinationLayout(slots=["wan1", "port1"])
        result = map_interfaces(ast, layout)
        self.assertEqual(result.warnings, [])
        out = render(ast)
        self.assertIn("# comentario inicial", out,
                      "el comentario inicial del bloque debe conservarse")
        self.assertIn("# comentario entre edits", out,
                      "el comentario desplazado debe emitirse, no descartarse")
        # el comentario interno de un edit tampoco debe perderse
        lines2 = [
            "config system interface",
            '    edit "wan1"',
            '        set vdom "root"',
            "        # comentario dentro del edit",
            '        set type physical',
            "    next",
            "end",
        ]
        ast2 = parse("\n".join(lines2) + "\n")
        map_interfaces(ast2, DestinationLayout(slots=["wan1"]))
        self.assertIn("# comentario dentro del edit", render(ast2))


class TestT4SubInterfaceRename(unittest.TestCase):
    """T4: referencias a subinterfaces 'old.subN' y el nombre del edit de la
    subinterface deben renombrarse junto con su padre."""

    def test_renamer_handles_subinterface_references(self):
        conf = _conf_iface(_iface_edit("port1") + _iface_edit("port2"))
        conf += _conf_ref_block("dstintf", '"port1.100"')
        ast = parse(conf)
        counts = rename_references(ast, {"port1": "port2"})
        out = render(ast)
        self.assertIn('set dstintf "port2.100"', out,
                      "la subinterface port1.100 debe renombrar a port2.100")
        self.assertNotIn('"port1.100"', out)
        self.assertEqual(counts.get("port1"), 1)

    def test_mapper_renames_subinterface_edit_with_parent(self):
        from core.engine import run_pipeline
        src_lines = [
            "#config-version=FGTTEST-7.4.12-FW-build2902-260505",
            "config system interface",
            '    edit "wan1"',
            '        set vdom "root"',
            '        set type physical',
            "    next",
            '    edit "port1"',
            '        set vdom "root"',
            '        set type physical',
            "    next",
            '    edit "port1.100"',
            '        set vdom "root"',
            '        set type vlan',
            '        set interface "port1"',
            "    next",
            "end",
            _conf_ref_block("dstintf", '"port1.100"').rstrip("\n"),
        ]
        src = "\n".join(src_lines) + "\n"
        template = make_backup_tpl(lan=[2, 3])
        result = run_pipeline(src, template, inject_admin=False, validate=False)
        # el padre se renombra port1 -> port2
        self.assertEqual(result.mapping.get("port1"), "port2")
        out = result.output_text
        self.assertIn('edit "port2.100"', out,
                      "el edit de la subinterface debe renombrarse con el padre")
        self.assertIn('set dstintf "port2.100"', out,
                      "la referencia a la subinterface debe renombrarse")
        self.assertNotIn('"port1.100"', out)
        # la referencia al padre dentro del edit de la subinterface tambien
        self.assertIn('set interface "port2"', out)


def make_backup_tpl(lan=None, wans=0):
    """Plantilla destino sintetica (sin WANs salvo indicacion)."""
    lan = lan or []
    lines = [
        "#config-version=FGTTEST-7.4.12-FW-build2902-260505",
        "config system interface",
    ]
    for i in range(1, wans + 1):
        lines += [f'    edit "wan{i}"', '        set vdom "root"',
                  '        set type physical', "    next"]
    for n in lan:
        lines += [f'    edit "port{n}"', '        set vdom "root"',
                  '        set type physical', "    next"]
    lines.append("end")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    unittest.main()
