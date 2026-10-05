"""Tests: hardening agnostico de modelo (round 2).

Casos de familia reales que el mapeador debe cubrir con el mismo codigo:
  - dmz1/dmz2 con role dmz (familia 600E) en vez de un literal "dmz".
  - puertos fisicos con role/vrf explicito que contradice su nombre
    (ej. "port9" con set role wan).
  - miembros de switch con fuentes planas (sin IP/dhcp/VLANs) que pueden
    auto-llenar su slot miembro; fuentes ruteadas quedan para decision
    del usuario.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.engine import run_pipeline, preview_reassignments


def _conf(iface_lines, switch_lines=None):
    lines = [
        "#config-version=FGTTEST-7.4.11-FW-build2878-260126:opmode=0:vdom=0:user=admin",
    ]
    if switch_lines:
        lines += ["config system switch-interface"] + switch_lines + ["end"]
    lines += ["config system interface"] + iface_lines + ["end"]
    lines += [
        "config system admin",
        '    edit "admin"',
        '        set accprofile "super_admin"',
        '        set vdom "root"',
        '        set password ENC dummy',
        '    next',
        "end",
    ]
    return "\n".join(lines) + "\n"


def _port(name, extra=()):
    out = [f'    edit "{name}"', '        set vdom "root"', '        set type physical']
    out += list(extra)
    out.append("    next")
    return out


class TestSpecialSlotsRealNames(unittest.TestCase):
    """H1: slots de clases especiales con nombres reales del template."""

    def test_dmz1_dmz2_keep_real_names(self):
        template = _conf(
            _port("wan")
            + _port("dmz1", ['set role dmz'])
            + _port("dmz2", ['set role dmz'])
            + _port("lan1")
        )
        src = _conf(_port("dmz", ['set role dmz']) + _port("lan1"))
        r = run_pipeline(src, template, inject_admin=False)
        self.assertIn("dmz1", r.layout.slots)
        self.assertIn("dmz2", r.layout.slots)
        self.assertNotIn("dmz", r.layout.slots)
        # el dmz del origen mapea real: dmz -> dmz1 (primer slot dmz)
        self.assertEqual(r.mapping.get("dmz"), "dmz1")
        self.assertEqual(r.mapping.get("lan1"), "lan1")

    def test_mgmt_real_name(self):
        template = _conf(
            _port("wan")
            + _port("oob", ['set dedicated-to management'])
        )
        r = run_pipeline(
            _conf(_port("oob", ['set dedicated-to management'])),
            template, inject_admin=False)
        self.assertIn("oob", r.layout.slots)
        self.assertNotIn("mgmt", r.layout.slots)
        self.assertEqual(r.mapping.get("oob"), "oob")

    def test_ha_real_names(self):
        template = _conf(_port("wan") + _port("ha1") + _port("ha2"))
        r = run_pipeline(
            _conf(_port("ha1") + _port("ha2") + _port("lan1")),
            template, inject_admin=False)
        self.assertEqual([s for s in r.layout.slots if s.startswith("ha")],
                         ["ha1", "ha2"])
        self.assertEqual(r.mapping.get("ha1"), "ha1")


class TestRoleFirstClassification(unittest.TestCase):
    """H2: type/role explicitos tienen prioridad sobre el prefijo del nombre."""

    def test_port_named_with_role_wan_goes_to_wan_pool(self):
        template = _conf(_port("wan1") + _port("port1") + _port("port2"))
        # el WAN del origen se llama port9 pero set role wan lo declara
        src = _conf(_port("port9", ['set role wan']) + _port("port1"))
        r = run_pipeline(src, template, inject_admin=False)
        self.assertEqual(r.mapping.get("port9"), "wan1")
        self.assertEqual(r.mapping.get("port1"), "port1")

    def test_dmz_named_with_role_dmz_maps_to_real_dmz_slot(self):
        template = _conf(_port("wan") + _port("dmz1", ['set role dmz']) + _port("lan1"))
        src = _conf(_port("dmz0", ['set role dmz']))
        r = run_pipeline(src, template, inject_admin=False)
        self.assertEqual(r.mapping.get("dmz0"), "dmz1")

    def test_role_lan_name_weird_gets_free_slot_or_discard(self):
        template = _conf(_port("wan") + _port("lan1"))
        src = _conf(_port("weird0", ['set role lan']) + _port("lan1"))
        r = run_pipeline(src, template, inject_admin=False)
        self.assertEqual(r.mapping.get("lan1"), "lan1")
        # weird0 es lan_port: sin otro slot libre queda descartado con aviso,
        # nunca tratado como WAN/DMZ por su nombre
        self.assertNotIn("weird0", r.mapping)
        self.assertTrue(any("weird0" in w for w in r.warnings))


class TestSwitchMemberPlainFill(unittest.TestCase):
    """H3: miembros de switch aceptan auto-fill solo de fuentes planas."""

    def _template_80f_style(self):
        switch = [
            '    edit "LAN"',
            '        set vdom "root"',
            '        set member "internal1" "internal2" "internal3" "internal4" "internal5"',
            '    next',
        ]
        iface = []
        iface += _port("wan1")
        iface += _port("wan2")
        for i in range(1, 6):
            iface += _port(f"internal{i}")
        iface += _port("internal6")
        iface += [
            '    edit "LAN"',
            '        set vdom "root"',
            '        set type switch',
            '        set member "internal1" "internal2" "internal3" "internal4" "internal5"',
            '    next',
        ]
        return _conf(iface, switch)

    def test_plain_source_fills_member_slot(self):
        src = _conf(
            _port("wan1", ['set role wan'])
            + _port("internal1")   # plano: sin ip, sin mode, sin vlans
            + _port("internal2"),
        )
        r = run_pipeline(src, self._template_80f_style(), inject_admin=False)
        self.assertEqual(r.mapping.get("wan1"), "wan1")
        self.assertEqual(r.mapping.get("internal1"), "internal1")
        self.assertEqual(r.mapping.get("internal2"), "internal2")

    def test_routed_source_on_member_identity_becomes_excedente(self):
        src = _conf(
            _port("wan1", ['set role wan'])
            + _port("internal1", ['set ip 192.168.1.1 255.255.255.0'])
            + _port("internal2"),
        )
        r = run_pipeline(src, self._template_80f_style(), inject_admin=False)
        # internal1 es ruteado y su slot propio es miembro de switch:
        # NO ocupa el miembro; la sugerencia (slot libre no miembro) se
        # aplica auto y el usuario puede re-elegir en la UI antes de procesar
        self.assertEqual(r.mapping.get("internal1"), "internal6")
        self.assertEqual(r.mapping.get("internal2"), "internal2")
        sug = {x["src_name"]: x["target_slot"]
               for x in preview_reassignments(src, self._template_80f_style())[0]}
        self.assertEqual(sug.get("internal1"), "internal6")

    def test_routed_source_no_fake_member_fill_when_plain_exists(self):
        # fuente ruteada con identidad miembro + fuente plana sin identidad:
        # la plana ocupa el slot libre, la ruteada queda para el usuario
        src = _conf(
            _port("wan1", ['set role wan'])
            + _port("internal1", ['set ip 192.168.1.1 255.255.255.0'])
            + _port("wired0"),
        )
        r = run_pipeline(src, self._template_80f_style(), inject_admin=False)
        # la ruteada NO ocupa el miembro: va por sugerencia al libre
        self.assertEqual(r.mapping.get("internal1"), "internal6")
        # la plana (intercambiable fisicamente) si puede ocupar el miembro
        self.assertEqual(r.mapping.get("wired0"), "internal1")


if __name__ == "__main__":
    unittest.main()
