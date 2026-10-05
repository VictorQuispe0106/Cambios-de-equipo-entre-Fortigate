"""Tests unitarios para template_parser."""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.template_parser import extract_layout, summarize, DestinationLayout


def make_template(wans=2, mgmt=False, dmz=False, ha=False, lan=None, lan_prefix="port",
                  logicals=None, modems=None, model_hint="100F"):
    """Genera un .conf de backup sintetico para usar como plantilla."""
    lan = lan or []
    logicals = logicals or []
    modems = modems or []
    lines = [
        f"#config-version=FGT{model_hint}-7.4.12-FW-build2902-260505:opmode=0:vdom=0:user=admin",
        "config system interface",
    ]
    for i in range(1, wans + 1):
        lines.append(f'    edit "wan{i}"')
        lines.append('        set vdom "root"')
        lines.append('        set type physical')
        lines.append('    next')
    if mgmt:
        lines.append('    edit "mgmt"')
        lines.append('        set vdom "root"')
        lines.append('        set type physical')
        lines.append('        set dedicated-to management')
        lines.append('    next')
    if dmz:
        lines.append('    edit "dmz"')
        lines.append('        set vdom "root"')
        lines.append('        set type physical')
        lines.append('        set role dmz')
        lines.append('    next')
    if ha:
        for i in range(1, 3):
            lines.append(f'    edit "ha{i}"')
            lines.append('        set vdom "root"')
            lines.append('        set type physical')
            lines.append('    next')
    for n in lan:
        name = f"{lan_prefix}{n}"
        lines.append(f'    edit "{name}"')
        lines.append('        set vdom "root"')
        lines.append('        set type physical')
        lines.append('    next')
    for name in modems:
        lines.append(f'    edit "{name}"')
        lines.append('        set vdom "root"')
        lines.append('        set type physical')
        lines.append('    next')
    for name in logicals:
        lines.append(f'    edit "{name}"')
        lines.append('        set vdom "root"')
        lines.append('        set type tunnel')
        lines.append('    next')
    lines.append("end")
    return "\n".join(lines) + "\n"


class TestExtractLayout(unittest.TestCase):

    def test_100F_template(self):
        text = make_template(wans=2, mgmt=True, dmz=True, ha=True, lan=list(range(1, 21)),
                             logicals=["naf.root", "ssl.root"], model_hint="100F")
        layout = extract_layout(text)
        self.assertEqual(layout.wan_count, 2)
        self.assertTrue(layout.has_mgmt)
        self.assertTrue(layout.has_dmz)
        self.assertTrue(layout.has_ha)
        self.assertEqual(layout.lan_count, 20)
        self.assertEqual(layout.lan_names[0], "port1")
        self.assertEqual(layout.lan_names[-1], "port20")
        self.assertEqual(len(layout.logical_names), 2)
        self.assertEqual(layout.model_hint, "100F")
        # Slots en orden canonico
        self.assertEqual(layout.slots[0], "dmz")
        self.assertEqual(layout.slots[1], "mgmt")
        self.assertEqual(layout.slots[2], "wan1")
        self.assertEqual(layout.slots[3], "wan2")
        self.assertEqual(layout.slots[4], "ha1")
        self.assertEqual(layout.slots[5], "ha2")
        self.assertEqual(layout.slots[6], "port1")
        self.assertEqual(layout.slots[-1], "port20")

    def test_80F_template_no_flags(self):
        text = make_template(wans=2, mgmt=False, dmz=False, ha=False, lan=list(range(1, 7)),
                             lan_prefix="internal", model_hint="80F")
        layout = extract_layout(text)
        self.assertEqual(layout.wan_count, 2)
        self.assertFalse(layout.has_mgmt)
        self.assertFalse(layout.has_dmz)
        self.assertFalse(layout.has_ha)
        self.assertEqual(layout.lan_count, 6)
        # Real names are kept: the mapper must emit names that exist on the
        # destination device, so internal1 stays internal1 (no portN rewrite).
        self.assertEqual(layout.lan_names,
                         ["internal1", "internal2", "internal3",
                          "internal4", "internal5", "internal6"])
        self.assertEqual(layout.model_hint, "80F")

    def test_lanN_naming_is_recognized(self):
        """Models named lan1..lanN (FGT 30G / FortiWiFi 40F family) must be
        detected as LAN slots instead of falling to misc physicals."""
        text = make_template(wans=1, lan=[1, 2, 3, 4], lan_prefix="lan",
                             model_hint="30G")
        layout = extract_layout(text)
        self.assertEqual(layout.lan_count, 4)
        self.assertEqual(layout.lan_names, ["lan1", "lan2", "lan3", "lan4"])
        self.assertEqual(layout._misc_physicals, [])

    def test_wan_slot_keeps_real_name(self):
        """A single WAN port named 'wan' must produce slot 'wan', not 'wan1'."""
        text = [
            "#config-version=FWF40F-7.4.11-FW-build2878-260126:opmode=0:vdom=0:user=admin",
            "config system interface",
            '    edit "wan"',
            '        set vdom "root"',
            '        set type physical',
            '    next',
            '    edit "lan1"',
            '        set vdom "root"',
            '        set type physical',
            '    next',
            "end",
        ]
        layout = extract_layout("\n".join(text) + "\n")
        self.assertEqual(layout.slots, ["wan", "lan1"])
        self.assertEqual(layout.wan_count, 1)

    def test_misc_physical_becomes_slot(self):
        """Physical non-canonical ports (ej. 'a') are real ports of the
        destination: they must be offered as mapable slots."""
        text = [
            "config system interface",
            '    edit "wan"',
            '        set vdom "root"',
            '        set type physical',
            '    next',
            '    edit "a"',
            '        set vdom "root"',
            '        set type physical',
            '    next',
            "end",
        ]
        layout = extract_layout("\n".join(text) + "\n")
        self.assertIn("a", layout.slots)
        self.assertEqual(layout.slots, ["wan", "a"])

    # ============================================================
    # T1 (model-agnostic hardening): los slots de clases especiales
    # (dmz/mgmt/ha) deben usar los NOMBRES REALES del template.
    # ============================================================

    def test_dmz_real_names_become_slots(self):
        """A template whose DMZ physicals are named dmz1/dmz2 with
        `set role dmz` must produce real-name slots, not a literal 'dmz'."""
        text = [
            "config system interface",
            '    edit "wan1"',
            '        set vdom "root"',
            '        set type physical',
            '    next',
            '    edit "dmz1"',
            '        set vdom "root"',
            '        set type physical',
            '        set role dmz',
            '    next',
            '    edit "dmz2"',
            '        set vdom "root"',
            '        set type physical',
            '        set role dmz',
            '    next',
            '    edit "port1"',
            '        set vdom "root"',
            '        set type physical',
            '    next',
            "end",
        ]
        layout = extract_layout("\n".join(text) + "\n")
        self.assertIn("dmz1", layout.slots)
        self.assertIn("dmz2", layout.slots)
        self.assertNotIn("dmz", layout.slots)
        # Orden canonico: dmz... antes de wan y lan
        self.assertEqual(layout.slots[:3], ["dmz1", "dmz2", "wan1"])
        self.assertTrue(layout.has_dmz)

    def test_mgmt_real_name_slot(self):
        """A management port named e.g. 'x1' (dedicated-to management) must
        produce a slot with its real name, not a literal 'mgmt'."""
        text = [
            "config system interface",
            '    edit "wan1"',
            '        set vdom "root"',
            '        set type physical',
            '    next',
            '    edit "x1"',
            '        set vdom "root"',
            '        set type physical',
            '        set dedicated-to management',
            '    next',
            '    edit "x2"',
            '        set vdom "root"',
            '        set type physical',
            '        set alias "VRF_GESTION"',
            '    next',
            '    edit "port1"',
            '        set vdom "root"',
            '        set type physical',
            '    next',
            "end",
        ]
        layout = extract_layout("\n".join(text) + "\n")
        self.assertIn("x1", layout.slots)
        self.assertIn("x2", layout.slots)
        self.assertNotIn("mgmt", layout.slots)
        self.assertTrue(layout.has_mgmt)
        # Orden canonico: dmz(no hay), mgmt, wan...
        self.assertEqual(layout.slots[:3], ["x1", "x2", "wan1"])

    def test_ha_real_name_slots(self):
        """HA physicals must use their collected real names as slots."""
        text = [
            "config system interface",
            '    edit "wan1"',
            '        set vdom "root"',
            '        set type physical',
            '    next',
            '    edit "ha1"',
            '        set vdom "root"',
            '        set type physical',
            '    next',
            '    edit "ha2"',
            '        set vdom "root"',
            '        set type physical',
            '    next',
            "end",
        ]
        layout = extract_layout("\n".join(text) + "\n")
        self.assertEqual(layout.slots[1:], ["ha1", "ha2"])
        self.assertTrue(layout.has_ha)

    def test_switch_members_detected(self):
        """Hardware switch interfaces of the template must be detected so the
        mapper can avoid auto-filling member ports and offer the switch as a
        reassignment target."""
        text = [
            "config system switch-interface",
            '    edit "LAN2_CLIENTE"',
            '        set vdom "root"',
            '        set member "lan1" "lan2"',
            "    next",
            "end",
            "config system interface",
            '    edit "wan"',
            '        set vdom "root"',
            '        set type physical',
            '    next',
            '    edit "lan1"',
            '        set vdom "root"',
            '        set type physical',
            '    next',
            '    edit "lan2"',
            '        set vdom "root"',
            '        set type physical',
            '    next',
            '    edit "lan3"',
            '        set vdom "root"',
            '        set type physical',
            '    next',
            '    edit "LAN2_CLIENTE"',
            '        set vdom "root"',
            '        set type switch',
            '        set member "lan1" "lan2"',
            '    next',
            "end",
        ]
        layout = extract_layout("\n".join(text) + "\n")
        self.assertEqual(layout.switch_members,
                         {"LAN2_CLIENTE": ["lan1", "lan2"]})
        self.assertEqual(layout.switch_names, ["LAN2_CLIENTE"])
        # Member ports remain slots (they physically exist) and the switch
        # itself is a logical interface, not a slot.
        self.assertIn("lan1", layout.slots)
        self.assertIn("lan2", layout.slots)
        self.assertNotIn("LAN2_CLIENTE", layout.slots)

    def test_modem_preserved(self):
        text = make_template(wans=2, mgmt=False, dmz=False, ha=False, lan=[1, 2, 3],
                             modems=["modem"])
        layout = extract_layout(text)
        self.assertIn("modem", layout.modem_names)
        self.assertEqual(layout.lan_count, 3)

    def test_logicals_preserved(self):
        text = make_template(wans=2, mgmt=False, dmz=False, ha=False, lan=[1, 2],
                             logicals=["naf.root", "l2t.root", "ssl.root"])
        layout = extract_layout(text)
        self.assertIn("naf.root", layout.logical_names)
        self.assertIn("l2t.root", layout.logical_names)
        self.assertIn("ssl.root", layout.logical_names)

    def test_empty_template_raises(self):
        with self.assertRaises(ValueError):
            extract_layout("")
        with self.assertRaises(ValueError):
            extract_layout("   ")

    def test_no_interface_section_raises(self):
        with self.assertRaises(ValueError):
            extract_layout("config system global\n    set hostname test\nend\n")

    def test_mgmt_by_alias(self):
        text = make_template(wans=2, mgmt=False, dmz=False, ha=False, lan=[1, 2])
        # Inyectar mgmt via alias en lugar de dedicated-to
        text = text.replace(
            '    edit "wan2"',
            '    edit "mgmt"\n        set vdom "root"\n        set type physical\n        set alias "VRF_GESTION"\n    next\n    edit "wan2"',
            1,
        )
        layout = extract_layout(text)
        self.assertTrue(layout.has_mgmt)

    def test_mgmt_by_vrf(self):
        text = make_template(wans=2, mgmt=False, dmz=False, ha=False, lan=[1, 2])
        text = text.replace(
            '    edit "wan2"',
            '    edit "mgmt"\n        set vdom "root"\n        set type physical\n        set vrf 12\n    next\n    edit "wan2"',
            1,
        )
        layout = extract_layout(text)
        self.assertTrue(layout.has_mgmt)

    def test_summarize(self):
        text = make_template(wans=2, mgmt=True, dmz=True, ha=True, lan=list(range(1, 11)),
                             logicals=["naf.root"], model_hint="100F")
        layout = extract_layout(text)
        s = summarize(layout)
        self.assertIn("10 puertos LAN", s)
        self.assertIn("mgmt", s)
        self.assertIn("dmz", s)
        self.assertIn("HA", s)


if __name__ == "__main__":
    unittest.main()