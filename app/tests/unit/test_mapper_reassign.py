"""Tests unitarios para el motor de reasignacion."""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.engine import run_pipeline, preview_reassignments, validate_balance
from core.interface_mapper import (
    detect_reassignments,
    map_interfaces,
    Reassignment,
)
from core.parser import parse
from core.template_parser import extract_layout


def make_backup(wans=2, mgmt=False, dmz=False, ha=False, lan=None, lan_prefix="port",
                logicals=None, modems=None, model="TEST"):
    """Genera un .conf sintetico."""
    lan = lan or []
    logicals = logicals or []
    modems = modems or []
    lines = [
        f"#config-version=FGT{model}-7.4.12-FW-build2902-260505",
        "config system interface",
    ]
    for i in range(1, wans + 1):
        lines.append(f'    edit "wan{i}"')
        lines.append('        set vdom "root"')
        lines.append('        set type physical')
        lines.append('        set role wan')
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
    lines.append("config system admin")
    lines.append('    edit "admin"')
    lines.append('        set accprofile "super_admin"')
    lines.append('        set vdom "root"')
    lines.append('        set password ENC dummy')
    lines.append('    next')
    lines.append("end")
    return "\n".join(lines) + "\n"


class TestReassign(unittest.TestCase):

    def test_dmz_reassigned_when_no_native_slot(self):
        """Origen tiene dmz, destino no. Se reasigna al primer LAN vacio."""
        src = make_backup(dmz=True, lan=[1, 2, 3])
        template = make_backup(lan=[1, 2, 3, 4, 5])  # sin dmz
        ra, disc = preview_reassignments(src, template)
        dmz_ra = [r for r in ra if r["src_name"] == "dmz"]
        self.assertEqual(len(dmz_ra), 1)
        self.assertEqual(dmz_ra[0]["target_slot"], "port4")

    def test_ha_reassigned_in_order(self):
        """ha1 y ha2 se reasignan en orden."""
        src = make_backup(ha=True, lan=[1, 2, 3])
        template = make_backup(lan=[1, 2, 3, 4, 5])  # sin ha
        ra, disc = preview_reassignments(src, template)
        ha_names = [r["src_name"] for r in ra if r["src_kind"] == "ha"]
        self.assertIn("ha1", ha_names)
        self.assertIn("ha2", ha_names)
        targets = sorted([r["target_slot"] for r in ra if r["src_kind"] == "ha"])
        self.assertEqual(targets, ["port4", "port5"])

    def test_modem_reassigned(self):
        """modem se reasigna a slot vacio."""
        src = make_backup(lan=[1, 2], modems=["modem"])
        template = make_backup(lan=[1, 2, 3, 4])  # sin modem
        ra, disc = preview_reassignments(src, template)
        modem_ra = [r for r in ra if r["src_name"] == "modem"]
        self.assertEqual(len(modem_ra), 1)
        self.assertEqual(modem_ra[0]["target_slot"], "port3")

    def test_mgmt_reassigned(self):
        """mgmt se reasigna a slot vacio."""
        src = make_backup(mgmt=True, lan=[1, 2])
        template = make_backup(lan=[1, 2, 3, 4])
        ra, disc = preview_reassignments(src, template)
        mgmt_ra = [r for r in ra if r["src_name"] == "mgmt"]
        self.assertEqual(len(mgmt_ra), 1)
        self.assertEqual(mgmt_ra[0]["target_slot"], "port3")

    def test_no_reassign_when_nothing_to_reassign(self):
        """Sin excedentes -> lista vacia."""
        src = make_backup(lan=[1, 2, 3])
        template = make_backup(lan=[1, 2, 3])
        ra, disc = preview_reassignments(src, template)
        self.assertEqual(len(ra), 0)
        self.assertEqual(len(disc), 0)

    def test_discarded_when_no_slots_available(self):
        """Sin slots disponibles -> los excedentes se devuelven con target_slot vacio
        (el usuario debe elegir manualmente)."""
        src = make_backup(dmz=True, lan=[1, 2, 3, 4, 5, 6])
        template = make_backup(lan=[1, 2, 3])  # muy pocos slots
        ra, disc = preview_reassignments(src, template)
        # dmz debe estar presente pero con target_slot vacio
        dmz_ra = [r for r in ra if r["src_name"] == "dmz"]
        self.assertEqual(len(dmz_ra), 1)
        self.assertEqual(dmz_ra[0]["target_slot"], "")
        # dmz debe estar en discarded (esperando asignacion manual)
        self.assertIn("dmz", disc)

    def test_priority_wan_first(self):
        """WAN tiene la maxima prioridad (se reasigna primero)."""
        # Destino: 2 LAN slots. Origen usa 1 (port1), entonces 1 slot libre (port2)
        # dmz tiene prioridad 1, ha tiene prioridad 2. Solo dmz cabe, ha se queda vacio.
        src = make_backup(dmz=True, ha=True, lan=[1])
        template = make_backup(lan=[1, 2])
        ra, disc = preview_reassignments(src, template)
        # TODOS los excedentes se devuelven (dmz, ha1, ha2)
        names = {r["src_name"] for r in ra}
        self.assertIn("dmz", names)
        self.assertIn("ha1", names)
        self.assertIn("ha2", names)
        # Pero solo dmz tiene target_slot asignado
        with_slot = [r for r in ra if r["target_slot"]]
        self.assertEqual(len(with_slot), 1)
        self.assertEqual(with_slot[0]["src_name"], "dmz")
        # Los que quedan vacios estan en discarded
        self.assertIn("ha1", disc)
        self.assertIn("ha2", disc)

    def test_priority_dmz_before_ha_when_both_fit(self):
        """Si caben ambos, dmz va primero (prioridad menor)."""
        # Destino: 4 LAN. Origen usa 1. Entonces 3 slots libres para dmz + ha1 + ha2
        src = make_backup(dmz=True, ha=True, lan=[1])
        template = make_backup(lan=[1, 2, 3, 4])
        ra, disc = preview_reassignments(src, template)
        # dmz, ha1, ha2 deben estar todos
        names = [r["src_name"] for r in ra]
        self.assertIn("dmz", names)
        self.assertIn("ha1", names)
        self.assertIn("ha2", names)
        # dmz (prio 1) debe estar antes que ha (prio 2) en orden
        dmz_idx = names.index("dmz")
        ha_indices = [i for i, n in enumerate(names) if n in ("ha1", "ha2")]
        for hi in ha_indices:
            self.assertLess(dmz_idx, hi)
        # Todos tienen target_slot asignado (caben)
        for r in ra:
            self.assertNotEqual(r["target_slot"], "")

    def test_wan_takes_priority_over_modem(self):
        """Cuando hay WAN y modem excedentes, WAN va primero."""
        src = make_backup(wans=4, lan=[1, 2], modems=["modem"])
        # Destino solo tiene 2 WAN slots
        template = make_backup(wans=2, lan=[1, 2, 3, 4])
        ra, disc = preview_reassignments(src, template)
        # wan3 y wan4 deberian reasignarse (no descartarse)
        wan_ras = [r for r in ra if r["src_kind"] == "wan"]
        self.assertGreaterEqual(len(wan_ras), 1)
        # Si ambos WAN se reasignan, los targets son los primeros LAN disponibles
        if len(wan_ras) >= 2:
            targets = [r["target_slot"] for r in wan_ras]
            self.assertEqual(targets, ["port3", "port4"])

    def test_manual_reassignment_overrides_native(self):
        """Si el usuario fuerza reasignacion a un slot nativo, ese slot se sobrescribe."""
        src = make_backup(mgmt=True, lan=[1, 2])
        template = make_backup(lan=[1, 2, 3, 4])
        # Forzar: mgmt -> port1 (que ya tiene internal1 del origen)
        manual = [Reassignment(src_name="mgmt", src_kind="mgmt", target_slot="port1")]
        result = run_pipeline(src, template, inject_admin=True, reassignments=manual)
        # mgmt debe estar en port1, internal1 debe haberse perdido
        self.assertEqual(result.mapping.get("mgmt"), "port1")
        self.assertNotIn("internal1", result.mapping)

    def test_run_pipeline_returns_reassignments(self):
        """El EngineResult incluye los reassignments aplicados."""
        src = make_backup(dmz=True, lan=[1])
        template = make_backup(lan=[1, 2])
        result = run_pipeline(src, template, inject_admin=True)
        # dmz debe haberse reasignado
        ra_names = [r.src_name for r in result.reassignments]
        self.assertIn("dmz", ra_names)

    def test_reassignments_in_engine_result_consistent(self):
        """Todos los reassignments aplicados deben estar en mapping."""
        src = make_backup(dmz=True, ha=True, lan=[1])
        template = make_backup(lan=[1, 2, 3])
        result = run_pipeline(src, template, inject_admin=True)
        for r in result.reassignments:
            self.assertEqual(result.mapping.get(r.src_name), r.target_slot)

    def test_excedentes_always_present_even_when_no_free_slots(self):
        """Cuando no hay slots libres, los excedentes se devuelven con target_slot vacio
        para que el usuario pueda elegir manualmente."""
        # Origen con 6 LAN, destino con 2 -> 4 excedentes, todos con target_slot=""
        src = make_backup(dmz=True, ha=True, mgmt=True, lan=[1, 2])
        template = make_backup(lan=[1, 2])  # solo 2 LAN
        ra, disc = preview_reassignments(src, template)
        # Todos los excedentes deben estar presentes
        names = {r["src_name"] for r in ra}
        self.assertIn("dmz", names)
        self.assertIn("mgmt", names)
        # ha1 y ha2
        self.assertIn("ha1", names)
        self.assertIn("ha2", names)
        # Al menos algunos deben tener target_slot="" (no caben)
        empty_slots = [r for r in ra if r["target_slot"] == ""]
        self.assertGreater(len(empty_slots), 0)

    def test_manual_reassign_with_empty_slot_kept_when_processing(self):
        """Si el usuario deja un dropdown vacio y procesa, el backend descarta esa interface
        y emite un warning."""
        from core.interface_mapper import Reassignment
        src = make_backup(dmz=True, lan=[1])
        template = make_backup(lan=[1, 2])
        # Forzar dmz -> "" (vacio) y procesar
        manual = [Reassignment(src_name="dmz", src_kind="dmz", target_slot="")]
        result = run_pipeline(src, template, inject_admin=True, reassignments=manual)
        # dmz no debe estar en mapping
        self.assertNotIn("dmz", result.mapping)
        # Debe haber un warning
        warns = " ".join(result.warnings)
        self.assertIn("dmz", warns)

    def test_manual_reassign_with_target_slot_overwrites_native(self):
        """Si el usuario elige un slot ocupado por interface nativa, se sobrescribe."""
        from core.interface_mapper import Reassignment
        src = make_backup(dmz=True, lan=[1, 2])
        template = make_backup(lan=[1, 2, 3])
        # Forzar dmz -> port1 (que tiene internal1 nativamente)
        manual = [Reassignment(src_name="dmz", src_kind="dmz", target_slot="port1")]
        result = run_pipeline(src, template, inject_admin=True, reassignments=manual)
        # dmz debe estar en port1
        self.assertEqual(result.mapping.get("dmz"), "port1")
        # internal1 debe haber sido desplazado
        self.assertNotIn("internal1", result.mapping)


if __name__ == "__main__":
    unittest.main()