import { test, expect } from '@playwright/test';
import { promises as fs } from 'fs';

const SAMPLE_80F = 'C:\\Users\\E758455\\Desktop\\Opencode-proyects\\CAMBIO DE EQUIPO AUTOMATIZACION\\Ejemplo_80F.conf';
const SAMPLE_60F = 'C:\\Users\\E758455\\Desktop\\Opencode-proyects\\CAMBIO DE EQUIPO AUTOMATIZACION\\Ejemplo_60F.conf';
const SAMPLE_100F = 'C:\\Users\\E758455\\Desktop\\Opencode-proyects\\CAMBIO DE EQUIPO AUTOMATIZACION\\Ejemplo_100F.conf';

// Origen: 100F con 4 portN (deja slots libres en destino 80F con 6 portN).
// Excedentes: dmz, ha1, ha2, mgmt. Slots libres: port5, port6.
// Reasignments automaticos esperados: dmz -> port5, ha1 -> port6.
const PLANTILLA_100F_4PORTS = [
  '#config-version=FGT100F-7.4.12',
  'config system interface',
  '    edit "wan1"',
  '        set type physical',
  '    next',
  '    edit "wan2"',
  '        set type physical',
  '    next',
  '    edit "mgmt"',
  '        set type physical',
  '        set dedicated-to management',
  '    next',
  '    edit "dmz"',
  '        set type physical',
  '    next',
  '    edit "ha1"',
  '        set type physical',
  '    next',
  '    edit "ha2"',
  '        set type physical',
  '    next',
];
for (let i = 1; i <= 4; i++) {
  PLANTILLA_100F_4PORTS.push(`    edit "port${i}"`);
  PLANTILLA_100F_4PORTS.push('        set type physical');
  PLANTILLA_100F_4PORTS.push('    next');
}
PLANTILLA_100F_4PORTS.push('end');
PLANTILLA_100F_4PORTS.push('config system admin');
PLANTILLA_100F_4PORTS.push('    edit "admin"');
PLANTILLA_100F_4PORTS.push('        set password ENC dummy');
PLANTILLA_100F_4PORTS.push('    next');
PLANTILLA_100F_4PORTS.push('end');
const TEMPLATE_PATH_100F_4PORTS = 'C:\\Users\\E758455\\AppData\\Local\\Temp\\plantilla_100f_4ports.conf';

test.describe('Reasignacion de interfaces excedentes (UI)', () => {
  test.beforeAll(async () => {
    await fs.writeFile(TEMPLATE_PATH_100F_4PORTS, PLANTILLA_100F_4PORTS.join('\n') + '\n', 'utf-8');
  });

  test('preview muestra propuesta automatica cuando hay slots libres', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
    page.on('console', (m) => { if (m.type() === 'error') errors.push(`console: ${m.text()}`); });

    // Subimos el 100F_small COMO PLANTILLA, y el 80F como origen (sin excedentes).
    // Espera: 80F (wan1/2 + internal1..6) -> 100F (wan1/2 + port1..4 + mgmt + dmz + ha1 + ha2)
    // Slots destino: dmz, mgmt, wan1, wan2, ha1, ha2, port1..4
    // Origen: wan1, wan2, internal1..6
    // Asignaciones nativas: wan1->wan1, wan2->wan2
    // Slots libres: dmz, mgmt, ha1, ha2, port1..4 (9 slots!)
    // Excedentes del origen: internal1..6 (6 interfaces, 6 slots libres)
    // Reasignments automaticos: internal1->port1, internal2->port2, ..., internal6->port6
    await page.goto('/');
    await page.setInputFiles('#fileInput', SAMPLE_80F);  // origen: 80F (wan + 6 internal)
    await page.setInputFiles('#templateInput', TEMPLATE_PATH_100F_4PORTS);  // destino: 100F

    // Esperar a que la seccion de reasignacion aparezca
    await expect(page.locator('#reassignSection')).not.toHaveClass(/hidden/, { timeout: 8000 });

    // Debe haber al menos 6 filas (internal1..internal6)
    const rows = await page.locator('.reassign-row').count();
    expect(rows).toBeGreaterThanOrEqual(6);

    // El status debe mencionar excedentes
    await expect(page.locator('#status')).toContainText(/excedentes|reasignac/i);

    expect(errors).toEqual([]);
  });

  test('preview sin excedentes: seccion oculta', async ({ page }) => {
    // 80F -> 100F: 100F tiene muchos slots, 80F tiene pocos. Sin excedentes.
    await page.goto('/');
    await page.setInputFiles('#fileInput', SAMPLE_80F);
    await page.setInputFiles('#templateInput', SAMPLE_100F);

    await page.waitForTimeout(500);
    const isHidden = await page.locator('#reassignSection').evaluate(el => el.classList.contains('hidden'));
    expect(isHidden).toBe(true);
  });

  test('cambiar un dropdown actualiza la asignacion', async ({ page }) => {
    await page.goto('/');
    await page.setInputFiles('#fileInput', SAMPLE_80F);
    await page.setInputFiles('#templateInput', TEMPLATE_PATH_100F_4PORTS);

    await expect(page.locator('#reassignSection')).not.toHaveClass(/hidden/, { timeout: 8000 });

    const firstSelect = page.locator('.reassign-select').first();
    const initialValue = await firstSelect.inputValue();
    const options = await firstSelect.locator('option').allTextContents();
    const alternative = options.find(o => o !== initialValue);
    expect(alternative).toBeTruthy();
    await firstSelect.selectOption(alternative);
    await expect(firstSelect).toHaveValue(alternative);
  });

  test('dropdowns duplicados se marcan en rojo', async ({ page }) => {
    await page.goto('/');
    await page.setInputFiles('#fileInput', SAMPLE_80F);
    await page.setInputFiles('#templateInput', TEMPLATE_PATH_100F_4PORTS);

    await expect(page.locator('#reassignSection')).not.toHaveClass(/hidden/, { timeout: 8000 });

    const rows = await page.locator('.reassign-row').count();
    if (rows < 2) test.skip(true, 'Necesita al menos 2 filas');

    const selects = page.locator('.reassign-select');
    const sameValue = await selects.nth(0).inputValue();
    await selects.nth(1).selectOption(sameValue);
    await page.waitForTimeout(200);

    const dupCount = await page.locator('.reassign-select.duplicate').count();
    expect(dupCount).toBeGreaterThanOrEqual(2);
  });

  test('procesar aplica las reasignaciones y muestra el conteo en status', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
    page.on('console', (m) => { if (m.type() === 'error') errors.push(`console: ${m.text()}`); });

    await page.goto('/');
    await page.setInputFiles('#fileInput', SAMPLE_80F);
    await page.setInputFiles('#templateInput', TEMPLATE_PATH_100F_4PORTS);

    await expect(page.locator('#reassignSection')).not.toHaveClass(/hidden/, { timeout: 8000 });

    await page.click('#btnProcess');
    await expect(page.locator('#status')).toContainText('Procesado OK', { timeout: 30000 });
    await expect(page.locator('#status')).toContainText(/reasignad/i);

    expect(errors).toEqual([]);
  });
});

test.describe('API reassignments', () => {
  test('preview devuelve array de reassignments cuando hay excedentes', async ({ request }) => {
    const fs = await import('fs/promises');
    const src = await fs.readFile(SAMPLE_80F, 'utf-8');
    const template = await fs.readFile(TEMPLATE_PATH_100F_4PORTS, 'utf-8');
    const r = await request.post('/api/preview-template', {
      data: { template, text: src },
    });
    expect(r.ok()).toBe(true);
    const j = await r.json();
    expect(j.ok).toBe(true);
    expect(Array.isArray(j.reassignments)).toBe(true);
    expect(Array.isArray(j.would_be_discarded)).toBe(true);
    expect(j.reassignments.length).toBeGreaterThan(0);
  });

  test('process con reassignments manuales via API', async ({ request }) => {
    const fs = await import('fs/promises');
    const src = await fs.readFile(SAMPLE_80F, 'utf-8');
    const template = await fs.readFile(SAMPLE_60F, 'utf-8');

    // Forzar: a (mgmt) -> port1 (sobrescribe internal1)
    const r = await request.post('/api/process', {
      data: {
        text: src,
        template,
        reassignments: [
          { src_name: 'a', src_kind: 'mgmt', target_slot: 'port1' },
        ],
      },
    });
    expect(r.ok()).toBe(true);
    const j = await r.json();
    expect(j.ok).toBe(true);
    expect(j.mapping.a).toBe('port1');
    expect(j.mapping.internal1).toBeUndefined();
    const applied = j.reassignments.find(x => x.src_name === 'a');
    expect(applied).toBeTruthy();
    expect(applied.target_slot).toBe('port1');
  });

  test('process sin reassignments: backward-compatible', async ({ request }) => {
    const fs = await import('fs/promises');
    const src = await fs.readFile(SAMPLE_80F, 'utf-8');
    const template = await fs.readFile(SAMPLE_100F, 'utf-8');
    const r = await request.post('/api/process', {
      data: { text: src, template },
    });
    expect(r.ok()).toBe(true);
    const j = await r.json();
    expect(j.ok).toBe(true);
    expect(j.would_be_discarded.length).toBe(0);
  });
});