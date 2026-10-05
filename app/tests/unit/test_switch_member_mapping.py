"""Tests: mapeo con miembros de switch de hardware (familia 30G/40F).

Escenario real BB49 -> BB53:
  Origen (FGT 30G): wan, lan1 (VLANs cliente), lan2 (WAN_4G dhcp), a (VRF).
  Destino (FortiWiFi 40F): wan, lan1+lan2 (miembros del switch LAN2_CLIENTE),
  lan3 libre, a, modem.

Regla de producto: la reubicacion la decide el usuario. Los slots miembros de
un switch no se auto-llenan con interfaces ruteadas; el switch es un destino
de reasignacion elegible en la UI.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.engine import run_pipeline, preview_reassignments
from core.interface_mapper import Reassignment


def make_src_30g() -> str:
    """Backup sintetico estilo FGT 30G."""
    lines = [
        "#config-version=FGT30G-7.4.11-FW-build2878-260126:opmode=0:vdom=0:user=admin",
        "config system interface",
        '    edit "wan"',
        '        set vdom "root"',
        '        set ip 190.119.105.66 255.255.255.248',
        '        set type physical',
        '        set alias "WAN_CLARO"',
        '        set role wan',
        '    next',
        '    edit "lan1"',
        '        set vdom "root"',
        '        set type physical',
        '        set description "Conectado al puerto 1 del SW Cliente"',
        '    next',
        '    edit "lan2"',
        '        set vdom "root"',
        '        set mode dhcp',
        '        set type physical',
        '        set alias "WAN_4G"',
        '    next',
        '    edit "a"',
        '        set vdom "root"',
        '        set ip 10.249.121.190 255.255.255.252',
        '        set allowaccess ping https ssh',
        '        set type physical',
        '        set alias "VRF_CLARO"',
        '    next',
        '    edit "VLAN_TIENDA"',
        '        set vdom "root"',
        '        set ip 10.86.49.100 255.255.255.0',
        '        set type vlan',
        '        set interface "lan1"',
        '        set vlanid 10',
        '    next',
        "end",
        "config system admin",
        '    edit "admin"',
        '        set accprofile "super_admin"',
        '        set vdom "root"',
        '        set password ENC dummy',
        '    next',
        "end",
    ]
    return "\n".join(lines) + "\n"


def make_tpl_40f() -> str:
    """Backup sintetico estilo FortiWiFi 40F con switch LAN2_CLIENTE."""
    lines = [
        "#config-version=FWF40F-7.4.11-FW-build2878-260126:opmode=0:vdom=0:user=admin",
        "config system switch-interface",
        '    edit "LAN2_CLIENTE"',
        '        set vdom "root"',
        '        set member "lan1" "lan2"',
        '    next',
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
        '    edit "a"',
        '        set vdom "root"',
        '        set type physical',
        '    next',
        '    edit "modem"',
        '        set vdom "root"',
        '        set status down',
        '        set type physical',
        '    next',
        '    edit "LAN2_CLIENTE"',
        '        set vdom "root"',
        '        set ip 10.86.53.100 255.255.255.0',
        '        set type switch',
        '        set member "lan1" "lan2"',
        '    next',
        "end",
        "config system admin",
        '    edit "admin"',
        '        set accprofile "super_admin"',
        '        set vdom "root"',
        '        set password ENC dummy',
        '    next',
        "end",
    ]
    return "\n".join(lines) + "\n"


def _iface_block(out: str, name: str) -> str:
    """Devuelve el bloque edit del name en config system interface del output."""
    marker = f'edit "{name}"'
    idx = out.find(marker)
    if idx < 0:
        return ""
    end = out.find("    next", idx)
    return out[idx:end]


class TestSwitchMemberMapping(unittest.TestCase):

    def test_auto_mapping_identity_and_excedentes(self):
        """wan y a mapean por identidad; lan1 recibe la sugerencia del primer
        slot libre no miembro (lan3) y lan2 queda sin slot: sin eleccion del
        usuario, se descarta con warning (nunca cae en un miembro de switch)."""
        r = run_pipeline(make_src_30g(), make_tpl_40f(), inject_admin=False)
        self.assertEqual(r.mapping.get("wan"), "wan")
        self.assertEqual(r.mapping.get("a"), "a")
        self.assertEqual(r.mapping.get("lan1"), "lan3")
        self.assertNotIn("lan2", r.mapping)
        # lan1 tiene sugerencia (primer slot libre no miembro); lan2 sin slot:
        # no se aplica (no aparece en reassignments) y queda como descartado
        ra = {x.src_name: x.target_slot for x in r.reassignments}
        self.assertEqual(ra.get("lan1"), "lan3")
        self.assertIsNone(ra.get("lan2"))
        self.assertIn("lan2", r.would_be_discarded)

    def test_reassign_to_switch_target(self):
        """Reasignar a un switch: el bloque se emite como switch con los
        miembros del template y las VLANs siguen al nuevo padre."""
        ras = [
            Reassignment(src_name="lan1", src_kind="lan_port",
                         target_slot="LAN2_CLIENTE"),
            Reassignment(src_name="lan2", src_kind="lan_port",
                         target_slot="lan3"),
        ]
        r = run_pipeline(make_src_30g(), make_tpl_40f(),
                         inject_admin=False, reassignments=ras)
        self.assertEqual(r.mapping.get("lan1"), "LAN2_CLIENTE")
        self.assertEqual(r.mapping.get("lan2"), "lan3")
        out = r.output_text
        sw_block = _iface_block(out, "LAN2_CLIENTE")
        self.assertIn("set type switch", sw_block)
        self.assertIn('set member "lan1" "lan2"', sw_block)
        # La VLAN que iba sobre lan1 ahora referencia al switch
        self.assertIn('set interface "LAN2_CLIENTE"', out)
        # El 4G mantiene su config sobre lan3
        lan3_block = _iface_block(out, "lan3")
        self.assertIn("set mode dhcp", lan3_block)
        self.assertIn('set alias "WAN_4G"', lan3_block)
        # Sin referencias huerfanas a lan1/lan2
        orphan_names = {o[1] for o in r.orphaned_refs}
        self.assertNotIn("lan1", orphan_names)
        self.assertNotIn("lan2", orphan_names)

    def test_user_can_override_member_slot(self):
        """Si el usuario elige explicitamente el slot miembro lan1, se respeta
        (bloque fisico con la config del origen)."""
        ras = [
            Reassignment(src_name="lan1", src_kind="lan_port",
                         target_slot="lan1"),
            Reassignment(src_name="lan2", src_kind="lan_port",
                         target_slot="lan3"),
        ]
        r = run_pipeline(make_src_30g(), make_tpl_40f(),
                         inject_admin=False, reassignments=ras)
        self.assertEqual(r.mapping.get("lan1"), "lan1")
        block = _iface_block(r.output_text, "lan1")
        self.assertIn("Conectado al puerto 1 del SW Cliente", block)
        self.assertIn("set type physical", block)

    def test_empty_member_slots_emitted(self):
        """Los slots miembros no consumidos quedan como bloques vacios, no
        desaparecen del output."""
        r = run_pipeline(make_src_30g(), make_tpl_40f(), inject_admin=False)
        self.assertIn('edit "lan1"', r.output_text)
        self.assertIn('edit "lan2"', r.output_text)


if __name__ == "__main__":
    unittest.main()
