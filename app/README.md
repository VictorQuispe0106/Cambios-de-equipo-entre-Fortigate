# Cambio de Equipo FortiGate

Migracion de backups `.conf` entre modelos FortiGate (ej. 80F -> 100F) ajustando
interfaces fisicas y agregando un usuario de administracion de respaldo. Funciona con **cualquier
modelo FortiGate** sin cambios de codigo: usa un backup de referencia del modelo
destino como plantilla.

## Uso

Doble clic en `iniciar.bat`. Se abrira automaticamente el navegador en:

    http://localhost:8765

Desde la UI:

1. **Carga el backup origen** (`.conf` del modelo actual).
2. **Carga el backup destino / plantilla** (`.conf` del modelo al que quieres pasar).
   La app detecta automaticamente sus interfaces (puertos, WAN, mgmt, dmz, HA)
   y las muestra en un preview antes de procesar.
3. Pulsa **Procesar backup**.
4. Revisa el log de mapeo, warnings y diff.
5. Pulsa **Descargar .conf**.

## Por que usa una plantilla?

El backup destino le dice al motor **exactamente** que interfaces tiene ese modelo
(dmz, mgmt, wan1..N, ha1, ha2, port1..N, modems, tuneles, etc.). Asi funciona con
cualquier modelo FortiGate actual o futuro, sin depender de un catalogo hardcoded.

El archivo `models.json` se conserva solo como referencia historica de modelos
comunes (40F, 60F, 80F, 100F, 100G, 200F, 400F, etc.) pero la app ya no lo usa.

## Estructura

```
app/
  iniciar.bat            # Lanzador (.bat)
  main.py                # Entry point Python
  server/app.py          # Servidor HTTP local (endpoints /api/*)
  core/                  # Motor de migracion
    parser.py            # .conf -> AST
    writer.py            # AST -> .conf
    template_parser.py   # Backup destino -> DestinationLayout
    interface_mapper.py  # Motor de mapeo
    renamer.py           # Reescribe referencias
    admin_injector.py    # Inyecta usuario admin de respaldo
    engine.py            # Orquestador
    model_detector.py    # Lee #Config-version= del backup
    interface_classifier.py
  web/                   # UI (HTML/CSS/JS)
    index.html
    styles.css
    app.js
  tests/
    unit/test_template_parser.py
  config/models.json     # Referencia (opcional)
```

## Reglas

- Solo se reescribe `config system interface` (interfaces fisicas) y se inyecta el usuario de administracion de respaldo en `config system admin`.
- `set snmp-index N` se elimina de las interfaces fisicas reescritas.
- Las interfaces logicas (naf.root, l2t.root, ssl.root, fortilink, LAN virtual switch, tuneles, agregados) se conservan tal cual.
- Si el destino tiene mas puertos que el origen, se generan bloques vacios `type physical`.
- Si el destino tiene menos puertos, los excedentes se descartan con warning.
- Las referencias a interfaces fisicas renombradas se actualizan automaticamente en el resto del archivo (`set member`, zones, policies, routes, etc.).
- Las referencias se renombran tambien en otras secciones (firewall policy, router static, etc.).

## API

```
GET  /                          -> UI
GET  /static/<file>             -> CSS/JS
GET  /sample/<file>             -> backups de ejemplo en el directorio padre
GET  /api/health                -> { ok: true }
POST /api/preview-template       -> analiza el backup destino y devuelve el layout detectado
POST /api/process               -> procesa (requiere 'text' y 'template')
POST /api/download              -> devuelve el .conf resultante como descarga
```

## Sin dependencias externas

Solo Python 3.x y un navegador moderno.

## Puerto

Por defecto `8765`. Para cambiarlo: `iniciar.bat 9000`.

## Tests

```bash
# Unit tests
python -m unittest tests.unit.test_template_parser

# E2E (Playwright)
npx playwright test  # desde playwright-tests/
```