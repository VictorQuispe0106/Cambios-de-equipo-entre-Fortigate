# 🔄 Cambio de Equipo entre FortiGate — Migrador de Backups

Herramienta que migra el **backup `.conf` de un FortiGate a otro modelo** (ej. 80F → 100F,
100F → 60F) ajustando automáticamente las interfaces físicas y conservando todas las
referencias. Funciona con **cualquier modelo FortiGate actual o futuro**: usa el backup
del equipo destino como plantilla — nada de catálogos hardcoded.

El flujo completo en un diagrama:

```mermaid
flowchart LR
    subgraph inputs["📥 Entradas"]
        direction TB
        SRC["🗂️ Backup origen<br/>conf del modelo actual"]
        TPL["🧩 Template destino<br/>conf del modelo nuevo"]
    end

    subgraph engine["⚙️ Motor de migración"]
        direction TB
        P["📄 parser<br/>conf → AST<br/>recursivo · multi-vdom"]
        TP["🧠 template_parser<br/>layout del modelo nuevo"]
        M{"🔀 interface_mapper<br/>para cada interfaz del orden:<br/>existe slot en el destino?"}
        R["🔁 renamer<br/>todas las refs en UNA pasada<br/>incl. sub-interfaces portN.subN"]
        AI["👤 admin_injector<br/>usuario admin claro<br/>idempotente"]
        W["💾 writer<br/>AST → conf"]
    end

    V{{"✅ config_validator<br/>huérfanas · balance · incompletos · dups"}}
    OUT[["📤 .conf mapeado y listo<br/>+ log de mapeo + warnings<br/>+ diff para revisión"]]

    SRC -->|"texto .conf"| P
    TPL -->|"layout destino"| TP
    P -->|AST| M
    TP -->|slots| M
    M -->|"mapping viejo → nuevo<br/>reescribe toda referencia"| R
    R --> AI --> W --> V
    V -->|"válido o con pendientes"| OUT

    M -- "descartes con motivo<br/>y slots libres" --> UI["🖥️ UI<br/>revisión + reasignación manual<br/>a cualquier tipo de slot"]
    UI -. "reasignaciones elegidas" .-> M

    classDef inp fill:#dbeafe,stroke:#1e40af,color:#0f172a,stroke-width:2px
    classDef stage fill:#dcfce7,stroke:#15803d,color:#0f172a,stroke-width:1px
    classDef gate fill:#fef9c3,stroke:#a16207,color:#0f172a,stroke-width:2px
    classDef outp fill:#f3e8ff,stroke:#7e22ce,color:#0f172a,stroke-width:2px
    classDef human fill:#fee2e2,stroke:#b91c1c,color:#0f172a,stroke-width:2px

    class SRC,TPL inp
    class P,TP,R,AI,W stage
    class M,V gate
    class OUT outp
    class UI human
```

> En GitHub este diagrama se dibuja solo (Mermaid nativo). Azul: entradas ·
> verde: etapas del motor · amarillo: decisiones y validación · violeta:
> resultado · rojo: tu revisión con reasignación manual (el lazo punteado) —
> si un excedente no tiene lugar, no se pierde en silencio: vuelve por la UI.

> En GitHub este diagrama se dibuja solo (Mermaid nativo). Si lo leés en texto
> plano: backup origen + template destino entran al motor (parser → mapper →
> renamer → admin injector → writer → validator) y salen un `.conf` mapeado y
> listo, con su log de mapeo, warnings y diff para que revises antes de subirlo
> al equipo nuevo.

## Cómo funciona

1. Cargás el **backup origen** (el `.conf` del modelo actual) y el **backup destino**
   (una template `.conf` del modelo al que querés pasar).
2. La app detecta el modelo de origen (`#config-version=`) y extrae el **layout de
   interfaces del destino** (puertos `portN`, `wan1..N`, `dmz`, `mgmt`, `ha1/ha2`,
   `modem`, y cualquier interfaz física no-canónica) desde la plantilla.
3. El motor:
   - **Renombra** interfaces: `internal` ⇄ `port`, `LAN` → nombre canónico del destino,
     con reescritura en **una sola pasada** (sin corrupción de encadenados
     `wan3→port4→port5`), incluyendo **sub-interfaces** (`port1.100` ⇄ `port2.100`).
   - **Descarta con aviso** lo que el destino no tiene (motivo explícito por interfaz,
     ej. "destino solo admite 6 puertos LAN"), y **crea vacíos** los slots nuevos.
   - **Reasigna** excedentes: automático (por prioridad wan < dmz < ha < mgmt < modem < lan)
     o **manual, a cualquier tipo de slot** (wan/dmz/mgmt/ha/modem incluidos).
   - **Renombra todas las referencias**: firewall policies, static routes, VPN/IPsec,
     DHCP servers, zones, aggregate/link-monitor members — y verifica que no queden
     **huérfanas** (con ignorancia correcta de macros `$(VDOM_LINKS)`, `*`, `any`).
   - **Inyecta** (opcional) el usuario admin `claro` en `config system admin`,
     idempotente, avisando si el perfil `super_admin` no existe en la plantilla.
   - **Valida** el output: balance de bloques, edits duplicados, configs incompletos
     (matching por token exacto), referencias a interfaces inexistentes.
4. Revisás el log de mapeo, warnings y diff, y descargás el `.conf` para restauraren el equipo nuevo.

## Estructura

```
CAMBIO DE EQUIPO AUTOMATIZACION/
├── app/
│   ├── iniciar.bat              # Lanzador → http://localhost:8765
│   ├── main.py                  # Entry point Python
│   ├── server/app.py            # Servidor HTTP local + API /api/*
│   ├── core/                    # Motor de migración
│   │   ├── parser.py              # .conf → AST lossless (recursivo, soporta multi-vdom)
│   │   ├── template_parser.py     # backup destino → DestinationLayout
│   │   ├── interface_mapper.py    # mapeo + reasignación + descartes razonados
│   │   ├── renamer.py             # renombrado en una sola pasada + orphans
│   │   ├── admin_injector.py      # usuario admin 'claro' idempotente
│   │   ├── config_validator.py    # validación de output
│   │   ├── model_detector.py      # modelon desde #config-version=
│   │   ├── engine.py              # orquestador (run_pipeline)
│   │   └── ...                    # interface_classifier, interface_mapper helpers
│   ├── web/                     # UI (HTML/CSS/JS nativo, sin build)
│   ├── config/models.json       # referencia histórica de modelos comunes
│   └── tests/unit/              # 61 tests (suite unittest)
├── playwright-tests/            # E2E (spec + config, requiere npx playwright)
└── AGENTS.md                    # brief original del proyecto
```

**No se versiona** (`.gitignore`): `node_modules/`, artifacts de Playwright (traces,
screenshots), outputs generados (`output_*.conf`) y tus **backups de ejemplo locales**
(`Ejemplo_*.conf`). Los cargás vos en la UI — no subas backups reales de producción
al repo.

## Arranque

```powershell
# Doble clic en app\iniciar.bat, o:
& "$env:LOCALAPPDATA\Microsoft\WindowsApps\python.exe" app\server\app.py 8765
```

Se abre `http://localhost:8765` automáticamente. Sin dependencias externas: solo
**Python 3.11+ stdlib** (probado en 3.14).

| Tarea | Cómo |
|---|---|
| Levantar la UI | `app\iniciar.bat` |
| Correr la suite de tests | `python -m unittest discover -s tests` (desde `app/`) |
| E2E con Playwright | `npx playwright test` (desde `playwright-tests/`) |

## API

| Endpoint | Descripción |
|---|---|
| `POST /api/preview-template` | Extrae y muestra el layout de la plantilla destino |
| `POST /api/dry-run` | Corre el pipeline sin escribir salida (validación previa) |
| `POST /api/process` | Migración completa; devuelve mapeo + warnings + diff |
| `POST /api/download` | Descarga del `.conf` generado |
| `GET /sample/<name>.conf` | Sirve cualquier `.conf` que dejes en la raíz del proyecto |
| `GET /api/health` | Health check |

## Notas de diseño

- **Modelo-agnóstico por diseño**: el layout del modelo destino se aprende de su
  backup, no de una tabla. Un modelo futuro solo requiere su backup como template.
- **Reasignación manual guiada por la herramienta**: si una interfaz del origen no
  tiene lugar en el destino (ej. pasar a un modelo con menos puertos), la UI propone
  reasignarlas a slots libres (cualquier tipo) o descartarlas con motivo — nada se
  pierde en silencio.
- **Multi-vdom**: backups con `config vdom`/`edit root` se procesan igualmente (el
  parser busca configs anidados recursivamente).
- **`x1`/`x2`, port13-14 discartes**: al pasar a un modelo con menos puertos, los
  puertos sobrantes se descartan **con aviso individual** y las referencias restantes
  quedan marcadas como huérfanas para que las atiendas antes de subir la config.

## Stack

Python 3.14 (stdlib only) · unittest · Playwright (E2E opcional) · HTML/CSS/JS nativo
