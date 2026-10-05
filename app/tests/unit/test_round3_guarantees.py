"""Round 3 guarantees para el motor de migracion (branch fix/any-model-round3).

T6: invariante de nombres inventados en runtime (engine).
T7: fuzz determinista any-model (se agrega en esta misma ronda).
T8: filtro de zonas para referencias huerfanas (renamer + engine).
"""

import os
import random
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.engine import run_pipeline
from core.renamer import (
    find_orphaned_references,
    get_interface_names_from_config,
)


def _iface_edit(name, lines=None):
    out = [f'    edit "{name}"', '        set vdom "root"',
           '        set type physical']
    for ln in (lines or []):
        out.append(f'        {ln}')
    out.append('    next')
    return out


def _conf_iface(edit_lines):
    return "\n".join(
        ["#config-version=FGTTEST-7.4.12-FW-build2902-260505",
         "config system interface"] + edit_lines + ["end"]
    ) + "\n"


def _policy_block(key, value):
    return "\n".join(
        ["config firewall policy",
         '    edit "1"',
         f'        set {key} {value}',
         "    next",
         "end"]
    ) + "\n"


class TestT6InventedNamesHelper(unittest.TestCase):
    """T6: helper de engine detecta nombres de interfaz inventados."""

    def test_helper_reports_ghost_name(self):
        """RED driver: un output con edit 'ghost1' (que no existe en origen
        ni plantilla) debe ser reportado por el helper."""
        from core.engine import check_invented_names
        source = _conf_iface(_iface_edit("port1", ["set role lan"]))
        template = _conf_iface(_iface_edit("port1", ["set role lan"]) +
                               _iface_edit("port2", ["set role lan"]))
        # output hand-written con un ghost
        output = _conf_iface(_iface_edit("port1") + _iface_edit("ghost1"))
        invented = check_invented_names(source, template, output)
        self.assertIn("ghost1", invented, msg=f"invented={invented}")

    def test_helper_clean_triple_is_empty(self):
        from core.engine import check_invented_names
        source = _conf_iface(_iface_edit("port1", ["set role lan"]))
        template = _conf_iface(_iface_edit("port1") + _iface_edit("port2"))
        output = _conf_iface(_iface_edit("port1") + _iface_edit("port2"))
        self.assertEqual(check_invented_names(source, template, output), [])


class TestT6PipelineWiring(unittest.TestCase):
    """T6: run_pipeline conecta el invariante a is_valid / errores."""

    def test_pipeline_mapping_to_unique_slot_no_invented(self):
        """Test 1: origen con 'src01' (lan_port), plantilla con solo 'wan1'
        como slot: el mapeo renombra a un nombre de la plantilla y no hay
        inventados ni errores."""
        source = _conf_iface(_iface_edit("src01", ["set role lan"]))
        template = _conf_iface(_iface_edit("wan1", ["set role wan"]))
        result = run_pipeline(source, template, inject_admin=False)
        out_names = get_interface_names_from_config(result.output_text)
        src_names = get_interface_names_from_config(source)
        tpl_names = get_interface_names_from_config(template)
        invented = out_names - src_names - tpl_names
        self.assertEqual(result.invented_interface_names, sorted(invented))
        self.assertFalse(invented, msg=f"invented={invented}")
        self.assertTrue(result.validation.is_valid,
                        msg=f"errors={result.validation.errors} "
                            f"orphaned={result.orphaned_refs}")

    def test_pipeline_positive_case_no_invented_names(self):
        """Caso positivo normal: pipeline normal no reporta inventados."""
        source = _conf_iface(_iface_edit("port1", ["set role lan"]) +
                             _iface_edit("port2", ["set role lan"]))
        template = _conf_iface(_iface_edit("port1") + _iface_edit("port2") +
                               _iface_edit("port3"))
        result = run_pipeline(source, template, inject_admin=False)
        self.assertEqual(result.invented_interface_names, [])
        self.assertTrue(result.validation.is_valid,
                        msg=f"errors={result.validation.errors} "
                            f"orphaned={result.orphaned_refs}")


class TestT8ZoneNamesHelper(unittest.TestCase):
    """T8: get_zone_names extrae zonas de system zone y system sdwan."""

    def test_zone_names_from_zone_and_sdwan(self):
        from core.renamer import get_zone_names
        text = (
            "config system sdwan\n"
            "    config zone\n"
            '        edit "Hub1"\n'
            "        next\n"
            '        edit "Hub2"\n'
            "        next\n"
            "    end\n"
            "end\n"
            "config system zone\n"
            '    edit "zone-internet"\n'
            "    next\n"
            "end\n"
        )
        self.assertEqual(get_zone_names(text),
                         {"Hub1", "Hub2", "zone-internet"})

    def test_zone_names_empty_without_zones(self):
        from core.renamer import get_zone_names
        text = _conf_iface(_iface_edit("port1"))
        self.assertEqual(get_zone_names(text), set())


def _zone_source():
    """Fuente sintetica con sdwan zones (Hub1/Hub2), system zone
    (zone-internet) y politicas que las referencian."""
    lines = [
        "#config-version=FGTTEST-7.4.12-FW-build2902-260505",
        "config system interface",
    ]
    lines += _iface_edit("wan1", ["set role wan"])
    lines += _iface_edit("port1", ["set role lan"])
    lines += ["end"]
    lines += [
        "config system sdwan",
        "    config zone",
        '        edit "Hub1"',
        "        next",
        '        edit "Hub2"',
        "        next",
        "    end",
        '    config service',
        '        edit "1"',
        '        set dstintf "Hub1"',
        "        next",
        "    end",
        "end",
        "config system zone",
        '    edit "zone-internet"',
        '        set interface "wan1"',
        "    next",
        "end",
        "config firewall policy",
        '    edit "1"',
        '        set dstintf "Hub1"',
        "    next",
        '    edit "2"',
        '        set dstintf "zone-internet"',
        "    next",
        "end",
    ]
    return "\n".join(lines) + "\n"


class TestT8PipelineZoneFilter(unittest.TestCase):
    """T8: run_pipeline no debe tratar zonas como interfaces huerfanas."""

    def test_pipeline_does_not_flag_zone_names_as_orphaned(self):
        source = _zone_source()
        template = _conf_iface(_iface_edit("wan1", ["set role wan"]) +
                               _iface_edit("port1", ["set role lan"]))
        result = run_pipeline(source, template, inject_admin=False)
        orphaned_names = {iface for _, iface, _ in result.orphaned_refs}
        self.assertNotIn("Hub1", orphaned_names,
                         msg=f"orphaned={result.orphaned_refs}")
        self.assertNotIn("Hub2", orphaned_names,
                         msg=f"orphaned={result.orphaned_refs}")
        self.assertNotIn("zone-internet", orphaned_names,
                         msg=f"orphaned={result.orphaned_refs}")
        self.assertTrue(result.validation.is_valid,
                        msg=f"errors={result.validation.errors} "
                            f"orphaned={result.orphaned_refs}")


FUZZ_SEED = 20261003
FUZZ_PAIRS = 40
FUZZ_TIME_BUDGET_S = 15


class TestAnyModelFuzz(unittest.TestCase):
    """T7: fuzz determinista any-model sobre run_pipeline."""

    @classmethod
    def setUpClass(cls):
        cls.rng = random.Random(FUZZ_SEED)
        cls.pairs = []
        for i in range(FUZZ_PAIRS):
            cls.pairs.append(cls._make_pair(cls.rng, i))

    # ---------- generador ----------

    @staticmethod
    def _iface_edit(name, lines):
        out = [f'    edit "{name}"', '        set vdom "root"']
        for ln in lines:
            out.append(f'        {ln}')
        out.append('    next')
        return out

    @classmethod
    def _make_pair(cls, rng, idx):
        """Construye (source_text, template_text, src_meta) aleatorios."""
        families = [
            ["wan"],
            ["wan1", "wan2"],
            [f"lan{n}" for n in range(1, 5)],
            [f"internal{n}" for n in range(1, 9)],
            [f"port{n}" for n in range(1, 21)],
            ["a", "b"],
        ]
        src_pool = list(rng.choice(families))
        for extra in range(rng.randint(0, 3)):
            src_pool.append(rng.choice(
                ["exotico7", "sfpX", "whatever0", f"exotico{extra}"]))
        dedup = list(dict.fromkeys(src_pool))
        rng.shuffle(dedup)

        # ---- origen ----
        src_lines = [
            f"#config-version=FGT{30 + idx % 70}G-7.4.12-FW-build2902-260505",
            "config system interface",
        ]
        src_meta = {}
        for j, name in enumerate(dedup):
            lines = ['set type physical']
            if name.lower().startswith("wan"):
                src_meta[name] = "wan"
                if rng.random() < 0.5:
                    lines.append(f'set role wan')
                lines.append(f'set ip 10.0.{j}.{20 + j} 255.255.255.0')
            elif name == "dmz":
                src_meta[name] = "dmz"
                lines.append('set role dmz')
            elif name == "mgmt":
                src_meta[name] = "mgmt"
                lines.append('set dedicated-to management')
            else:
                src_meta[name] = "lan"
                if rng.random() < 0.3:
                    lines.append(f'set role {rng.choice(["lan", "dmz", "wan"])}')
            if rng.random() < 0.25:
                src_meta[name] = "dhcp"
                lines.append('set mode dhcp')
            src_lines += cls._iface_edit(name, lines)

        if dedup and rng.random() < 0.5:
            parent = rng.choice(dedup)
            vname = f"vlan{idx}child"
            src_lines += cls._iface_edit(vname, [
                'set type vlan', f'set interface "{parent}"',
                f'set vlanid {10 + idx}',
            ])
            src_meta[vname] = "vlan"
        src_lines.append("end")
        src_lines += [
            "config system admin",
            '    edit "admin"',
            '        set accprofile "super_admin"',
            '        set vdom "root"',
            '        set password ENC dummy',
            '    next',
            "end",
        ]
        source = "\n".join(src_lines) + "\n"

        # ---- plantilla ----
        tpl_pool = list(rng.choice(families))
        tpl_names = list(dict.fromkeys(
            tpl_pool + [n for n in dedup if rng.random() < 0.4]))
        rng.shuffle(tpl_names)
        tpl_lines = [
            f"#config-version=FWF{40 + idx % 60}F-7.4.12-FW-build2902-260505",
        ]

        if tpl_names and rng.random() < 0.5:
            for sw_i in range(rng.randint(1, 2)):
                members = rng.sample(
                    tpl_names, k=min(len(tpl_names), rng.randint(1, 3)))
                if not members:
                    continue
                sw_name = f"SW{sw_i}_{idx}"
                tpl_lines += [
                    "config system switch-interface",
                    f'    edit "{sw_name}"',
                    '        set vdom "root"',
                    '        set member ' + " ".join(f'"{m}"' for m in members),
                    '    next',
                    "end",
                ]

        tpl_lines.append("config system interface")
        for name in tpl_names:
            lines = ['set type physical']
            if name.lower().startswith("wan"):
                if rng.random() < 0.5:
                    lines.append('set role wan')
            elif name == "dmz":
                lines.append('set role dmz')
            elif name == "mgmt":
                lines.append('set dedicated-to management')
            tpl_lines += cls._iface_edit(name, lines)
        for lg in ("ssl.root", "naf.root"):
            tpl_lines += cls._iface_edit(lg, ['set type tunnel'])
        tpl_lines.append("end")
        tpl_lines += [
            "config system admin",
            '    edit "admin"',
            '        set accprofile "super_admin"',
            '        set vdom "root"',
            '        set password ENC dummy',
            '    next',
            "end",
        ]
        template = "\n".join(tpl_lines) + "\n"
        return source, template, src_meta

    # ---------- invariantes ----------

    def test_fuzz_pipeline_invariants(self):
        started = time.time()
        failures = []
        for i, (source, template, src_meta) in enumerate(self.pairs):
            try:
                result = run_pipeline(source, template, inject_admin=False)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"pair {i}: excepcion {exc!r}")
                continue
            src_names = get_interface_names_from_config(source)
            tpl_names = get_interface_names_from_config(template)
            out_names = get_interface_names_from_config(result.output_text)
            bad = out_names - src_names - tpl_names
            if bad:
                failures.append(f"pair {i}: nombres inventados {sorted(bad)}")
            src_wans = {n for n, kind in src_meta.items() if kind == "wan"}
            # una WAN migrada aparece en el mapping (renombrada); solo las
            # que NO estan ni en el output ni en el mapping fueron descartadas
            migrated = set(result.mapping.keys())
            dropped_wans = src_wans - out_names - migrated
            warnings_text = "\n".join(result.warnings)
            for name in dropped_wans:
                if name not in warnings_text:
                    failures.append(
                        f"pair {i}: WAN '{name}' descartada sin warning")
        elapsed = time.time() - started
        if failures:
            dump = os.path.join(
                os.environ.get("TEMP", "."),
                f"fuzz_round3_failure_{FUZZ_SEED}.txt")
            with open(dump, "w", encoding="utf-8") as fh:
                for i, (source, template, _s) in enumerate(self.pairs):
                    fh.write(f"===== pair {i} source =====\n{source}\n")
                    fh.write(f"===== pair {i} template =====\n{template}\n")
            self.fail(
                "; ".join(failures)
                + f" | inputs volcados en {dump}")
        self.assertLess(
            elapsed, FUZZ_TIME_BUDGET_S,
            msg=f"fuzz tomo {elapsed:.1f}s (limite {FUZZ_TIME_BUDGET_S}s); "
                "reducir FUZZ_PAIRS a 20")


if __name__ == "__main__":
    unittest.main()
