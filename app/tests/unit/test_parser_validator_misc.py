"""Tests unitarios T6-T10b: parser multi-vdom, admin_injector, template_parser,
config_validator y model_detector."""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.parser import parse, find_config
from core.writer import render
from core.admin_injector import inject_claro


_NESTED_VDOM_ADMIN = """#config-version=FGT80F-7.4.12-FW-build2902-260505:opmode=0:vdom=0:user=USER_N2LDAP
#global_vdom=1
config system global
    set hostname gw-old
end
config vdom
    edit root
        config system admin
            edit "admin"
                set vdom "root"
                set accprofile "super_admin"
            next
        end
    next
end
"""


class TestT6MultiVdomNestedConfig(unittest.TestCase):
    """T6: find_config debe encontrar configs anidados dentro de edit (multi-vdom)."""

    def test_find_config_finds_nested_section(self):
        ast = parse(_NESTED_VDOM_ADMIN)
        cfg = find_config(ast, "system admin")
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.meta.get("name"), "system admin")

    def test_root_level_match_preferred_when_duplicated(self):
        text = (
            'config system admin\n    edit "admin"\n'
            '        set accprofile "super_admin"\n    next\nend\n'
            'config vdom\n    edit root\n        config system admin\n'
            '            edit "nested-admin"\n            next\n        end\n'
            '    next\nend\n'
        )
        ast = parse(text)
        cfg = find_config(ast, "system admin")
        self.assertIsNotNone(cfg)
        # Debe ser el de nivel raiz: su padre es el nodo root, no un edit
        self.assertEqual(cfg.parent.kind, "root")
        names = [c.meta.get("name") for c in cfg.children if c.kind == "edit"]
        self.assertEqual(names, ["admin"])

    def test_inject_claro_into_nested_vdom_block(self):
        ast = parse(_NESTED_VDOM_ADMIN)
        injected = inject_claro(ast)
        self.assertTrue(injected)
        out = render(ast)
        self.assertIn('edit "claro"', out)
        self.assertIn('set accprofile "super_admin"', out)
        self.assertIn('set vdom "root"', out)

    def test_inject_claro_double_inject_idempotent(self):
        ast = parse(_NESTED_VDOM_ADMIN)
        self.assertTrue(inject_claro(ast))
        self.assertFalse(inject_claro(ast))
        out = render(ast)
        self.assertEqual(out.count('edit "claro"'), 1)

    def test_inject_claro_never_overwrites_existing_claro(self):
        text = _NESTED_VDOM_ADMIN.replace(
            '        config system admin\n',
            '        config system admin\n'
            '            edit "claro"\n'
            '                set accprofile "no_super"\n'
            '                set vdom "root"\n'
            '            next\n',
            1,
        )
        ast = parse(text)
        injected = inject_claro(ast)
        out = render(ast)
        self.assertFalse(injected)
        self.assertEqual(out.count('edit "claro"'), 1)
        self.assertIn('set accprofile "no_super"', out)
class TestT7AdminInjectorCleanup(unittest.TestCase):
    """T7: factoria unica del bloque claro + comportamiento sin accprofile."""

    def test_dead_constant_removed(self):
        import core.admin_injector as ai
        self.assertFalse(hasattr(ai, "CLARO_BLOCK_LINES"))

    def test_output_lines_identical_after_constant_removal(self):
        # El bloque generado debe seguir siendo el mismo literal canonico
        # (env dummy para el password: determinista, nunca commitea el real)
        import os
        old = os.environ.get("FORTIGATE_ADMIN_PASSWORD_ENC")
        os.environ["FORTIGATE_ADMIN_PASSWORD_ENC"] = "ENC DUMMYTESTENC=="
        try:
            ast = parse('config system admin\n    edit "admin"\n    next\nend\n')
            self.assertTrue(inject_claro(ast))
            out = render(ast)
            expected = [
                '    edit "claro"',
                '        set accprofile "super_admin"',
                '        set vdom "root"',
                '        set password ENC DUMMYTESTENC==',
            ]
            for line in expected:
                self.assertIn(line, out)
        finally:
            if old is None:
                os.environ.pop("FORTIGATE_ADMIN_PASSWORD_ENC", None)
            else:
                os.environ["FORTIGATE_ADMIN_PASSWORD_ENC"] = old



class TestT8ModemBucket(unittest.TestCase):
    """T8: solo nombres modem* van al bucket modem; otros fisicos no canonicos
    van a _misc_physicals."""

    def _tpl(self, extra_names):
        base = (
            "config system interface\n"
            '    edit "port1"\n                set vdom "root"\n                set type physical\n            next\n'
            '    edit "port2"\n                set vdom "root"\n                set type physical\n            next\n'
        )
        for n in extra_names:
            base += f'    edit "{n}"\n        set vdom "root"\n        set type physical\n    next\n'
        return base + "end\n"

    def test_only_modem_star_in_modem_names(self):
        from core.template_parser import extract_layout
        layout = extract_layout(self._tpl(["fortilink", "a", "modem1"]))
        self.assertEqual(layout.modem_names, ["modem1"])

    def test_misc_physicals_captures_others(self):
        from core.template_parser import extract_layout
        layout = extract_layout(self._tpl(["fortilink", "a", "modem1", "MODEM2"]))
        # MODEM2 es modem (case-insensitive); fortilink y "a" no
        self.assertEqual(sorted(layout.modem_names), ["MODEM2", "modem1"])
        self.assertTrue(hasattr(layout, "_misc_physicals"))
        self.assertEqual(sorted(layout._misc_physicals), ["a", "fortilink"])

    def test_modem_case_insensitive(self):
        from core.template_parser import extract_layout
        layout = extract_layout(self._tpl(["MODEM2", "Modem-Backup"]))
        sorted_modems = sorted(layout.modem_names)
        self.assertEqual(sorted_modems, ["MODEM2", "Modem-Backup"])



class TestT9IncompleteConfigTokenMatch(unittest.TestCase):
    """T9: suprimir solo con coincidencia de TOKEN completo del nombre de config."""

    def test_exact_token_suppressed(self):
        from core.config_validator import validate_config
        r = validate_config("config system sip\nend\n")
        self.assertFalse(any("vacío" in w for w in r.warnings), msg=r.warnings)

    def test_substring_not_suppressed(self):
        from core.config_validator import validate_config
        r = validate_config("config firewall sip-policy\nend\n")
        self.assertTrue(any("sip-policy" in w and "vacío" in w for w in r.warnings))

    def test_other_known_keys_still_work(self):
        from core.config_validator import validate_config
        # clave multi-palabra: coincidencia de ruta completa
        r = validate_config("config system replacemsg\nend\n")
        self.assertFalse(any("vacío" in w for w in r.warnings), msg=r.warnings)



class TestT9OrphanMemberCheck(unittest.TestCase):
    """T9: set member como ref a interfaz solo en contextos concretos."""

    def _iface(self, name):
        return (
            f'    edit "{name}"\n            set vdom "root"\n            set type physical\n        next\n'
        )

    def test_link_monitor_bad_member_warns(self):
        from core.config_validator import validate_config
        text = (
            "config system interface\n"
            + self._iface("port1") + self._iface("port2")
            + "end\n"
            "config system link-monitor\n"
            '    edit "lm1"\n        set member "nonexistent-iface"\n    next\n'
            "end\n"
        )
        r = validate_config(text)
        self.assertTrue(
            any("nonexistent-iface" in w for w in r.warnings),
            msg=f"warnings={r.warnings}",
        )

    def test_link_monitor_good_member_no_warning(self):
        from core.config_validator import validate_config
        text = (
            "config system interface\n"
            + self._iface("port1") + self._iface("port2")
            + "end\n"
            "config system link-monitor\n"
            '    edit "lm1"\n        set member "port1"\n    next\n'
            "end\n"
        )
        r = validate_config(text)
        self.assertFalse(any("port1" in w and "definida" in w for w in r.warnings),
                         msg=f"warnings={r.warnings}")

    def test_address_group_member_no_warning(self):
        from core.config_validator import validate_config
        text = (
            "config system interface\n"
            + self._iface("port1")
            + "end\n"
            "config firewall address\n"
            '    edit "grp1"\n        set member "nonexistent-iface"\n    next\n'
            "end\n"
        )
        r = validate_config(text)
        self.assertFalse(
            any("nonexistent-iface" in w for w in r.warnings),
            msg=f"warnings={r.warnings}",
        )

    def test_service_group_member_no_warning(self):
        from core.config_validator import validate_config
        text = (
            "config system interface\n"
            + self._iface("port1")
            + "end\n"
            "config firewall service group\n"
            '    edit "svcgrp"\n        set member "DNS" "HTTP"\n    next\n'
            "end\n"
        )
        r = validate_config(text)
        self.assertFalse(
            any("DNS" in w and "definida" in w for w in r.warnings),
            msg=f"warnings={r.warnings}",
        )

    def test_aggregate_bad_member_warns(self):
        from core.config_validator import validate_config
        text = (
            "config system interface\n"
            + self._iface("port1")
            + '    edit "agg1"\n        set vdom "root"\n        set type aggregate\n        set member "ghost-iface"\n    next\n'
            "end\n"
        )
        r = validate_config(text)
        self.assertTrue(
            any("ghost-iface" in w for w in r.warnings),
            msg=f"warnings={r.warnings}",
        )

    def test_virtual_switch_bad_member_warns(self):
        from core.config_validator import validate_config
        text = (
            "config system interface\n"
            + self._iface("port1")
            + "end\n"
            "config system virtual-switch\n"
            '    edit "vs1"\n        set member "ghost-iface"\n    next\n'
            "end\n"
        )
        r = validate_config(text)
        self.assertTrue(
            any("ghost-iface" in w for w in r.warnings),
            msg=f"warnings={r.warnings}",
        )

    def test_zone_bad_member_warns(self):
        from core.config_validator import validate_config
        text = (
            "config system interface\n"
            + self._iface("port1")
            + "end\n"
            "config system zone\n"
            '    edit "zone1"\n        set member "ghost-iface"\n    next\n'
            "end\n"
        )
        r = validate_config(text)
        self.assertTrue(
            any("ghost-iface" in w for w in r.warnings),
            msg=f"warnings={r.warnings}",
        )



class TestT10ModelDetector(unittest.TestCase):
    """T10: escaneo de 40 líneas, variantes FGT_/FG-, basura -> None."""

    def test_fg_hyphen_form_detected(self):
        from core.model_detector import detect_model
        text = "#config-version=FG-100F-7.4.11-FW-build2878-260126:opmode=0:vdom=0:user=admin\n"
        self.assertEqual(detect_model(text), "100F")

    def test_fgt_underscore_form_detected(self):
        from core.model_detector import detect_model
        text = "#config-version=FGT_80F-7.4.12-FW-build2902-260505:opmode=0:vdom=0:user=admin\n"
        self.assertEqual(detect_model(text), "80F")

    def test_classic_forms_still_detected(self):
        from core.model_detector import detect_model
        self.assertEqual(
            detect_model("#config-version=FGT80F-7.4.12-FW-build2902-260505:opmode=0:vdom=0:user=x\n"),
            "80F",
        )
        self.assertEqual(
            detect_model("#config-version=FG100F-7.4.11-FW-build2878-260126:opmode=0:vdom=0:user=x\n"),
            "100F",
        )

    def test_header_beyond_10_lines_detected(self):
        from core.model_detector import detect_model
        text = "\n" * 29 + "#config-version=FGT_60F-7.2.0-FW-build1-1:opmode=0:vdom=0:user=x\n"
        self.assertEqual(detect_model(text), "60F")

    def test_header_at_line_31_detected(self):
        from core.model_detector import detect_model
        text = "\n" * 30 + "#config-version=FG100F-7.4.11-FW-build2878-260126:opmode=0:vdom=0:user=x\n"
        self.assertEqual(detect_model(text), "100F")

    def test_garbage_returns_none(self):
        from core.model_detector import detect_model
        self.assertIsNone(detect_model("no header at all\nconfig system global\nend\n"))
        self.assertIsNone(detect_model(""))



if __name__ == "__main__":
    unittest.main()
