"""
Detector de modelo FortiGate a partir del header #config-version=.

Ejemplos:
  #config-version=FGT80F-7.4.12-FW-build2902-260505:opmode=0:vdom=0:user=USER_N2LDAP
  #config-version=FG100F-7.4.11-FW-build2878-260126:opmode=0:vdom=0:user=USER_N2LDAP
"""

from __future__ import annotations
import re
from typing import Optional


VERSION_RE = re.compile(r"#config-version=\s*(FG[GT]*[ _-]?\d+[A-Z])")


def detect_model(text: str) -> Optional[str]:
    """
    Devuelve el identificador de modelo (ej. '80F', '100F') o None si no se detecta.

    Escanea las primeras 40 líneas (los headers pueden venir retrasados en
    backups multi-vdom / con encabezados extra) y acepta variantes de header:
      - #config-version=FGT80F-...   (forma clásica)
      - #config-version=FG100F-...
      - #config-version=FGT_80F-...  (con guion bajo)
      - #config-version=FG-100F-...  (con guion)
    Si el texto no contiene un header reconocible (basura), devuelve None.
    """
    for line in text.splitlines()[:40]:
        m = VERSION_RE.search(line)
        if m:
            token = m.group(1)
            # FGT80F -> 80F, FG100F -> 100F, FGT_80F -> 80F, FG-100F -> 100F
            digits = re.search(r"\d+F", token)
            if digits:
                return digits.group(0)
    return None