"""
Detector de modelo FortiGate a partir del header #config-version=.

Ejemplos:
  #config-version=FGT80F-7.4.12-FW-build2902-260505:opmode=0:vdom=0:user=USER_N2LDAP
  #config-version=FG100F-7.4.11-FW-build2878-260126:opmode=0:vdom=0:user=USER_N2LDAP
"""

from __future__ import annotations
import re
from typing import Optional


VERSION_RE = re.compile(r"#config-version=(FGT?\d+F[A-Z]?)")


def detect_model(text: str) -> Optional[str]:
    """Devuelve el identificador de modelo (ej. '80F', '100F') o None si no se detecta."""
    for line in text.splitlines()[:10]:
        m = VERSION_RE.search(line)
        if m:
            token = m.group(1)
            # FGT80F -> 80F, FG100F -> 100F
            digits = re.search(r"\d+F", token)
            if digits:
                return digits.group(0)
    return None