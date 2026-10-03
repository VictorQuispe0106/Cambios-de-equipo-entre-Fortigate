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
        # internal1 -> port1, internal6 -> port6
        self.assertEqual(layout.lan_names, ["port1", "port2", "port3", "port4", "port5", "port6"])
        self.assertEqual(layout.model_hint, "80F")

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