import { test, expect } from '@playwright/test';

const SAMPLE_PATH = 'C:\\Users\\E758455\\Desktop\\Opencode-proyects\\CAMBIO DE EQUIPO AUTOMATIZACION\\Ejemplo_80F.conf';

test.describe('Cambio de Equipo FortiGate - modo plantilla', () => {
  test('carga inicial: 3 secciones + boton Procesar deshabilitado', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
    page.on('console', (m) => { if (m.type() === 'error') errors.push(`console: ${m.text()}`); });

    await page.goto('/');
    await expect(page).toHaveTitle(/Cambio de Equipo FortiGate/);

    // 3 secciones (headings)
    await expect(page.getByRole('heading', { name: 'Backup origen' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Backup destino (plantilla)' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Opciones' })).toBeVisible();

    // Boton Procesar deshabilitado (sin backups)
    await expect(page.locator('#btnProcess')).toBeDisabled();
    await expect(page.locator('#btnDownload')).toBeDisabled();

    // Status inicial
    await expect(page.locator('#status')).toContainText(/Carga ambos backups/);
    await expect(page.locator('#templatePreview')).toContainText(/Aun no se ha detectado|Aún no se ha detectado/);

    expect(errors).toEqual([]);
  });

  test('cargar ejemplo 80F como origen funciona', async ({ page }) => {
    await page.goto('/');
    await page.click('#loadSample');
    await expect(page.locator('#fileMeta')).toContainText('Ejemplo_80F.conf', { timeout: 10000 });
    await expect(page.locator('#fileLabel')).toContainText('Ejemplo_80F.conf');
    // El boton Procesar sigue deshabilitado (falta plantilla)
    await expect(page.locator('#btnProcess')).toBeDisabled();
  });

  test('preview de plantilla al subir Ejemplo_100F.conf', async ({ page }) => {
    await page.goto('/');
    await page.setInputFiles('#templateInput', SAMPLE_PATH); // usamos el 80F como "plantilla" de ejemplo

    // El preview debe detectar interfaces (texto "puertos LAN")
    await expect(page.locator('#templatePreview')).toContainText(/puertos LAN/, { timeout: 5000 });
    // La clase 'detected' debe estar aplicada
    await expect(page.locator('#templatePreview')).toHaveClass(/detected/);
    // El boton Procesar sigue deshabilitado (falta origen)
    await expect(page.locator('#btnProcess')).toBeDisabled();
  });

  test('preview sin archivo configurado: mensaje vacio', async ({ page }) => {
    await page.goto('/');
    const text = await page.locator('#templatePreview').innerText();
    expect(text).toMatch(/Aun no se ha detectado|Aún no se ha detectado/);
  });

  test('preview detecta correctamente: al subir ejemplo 80F como plantilla', async ({ page }) => {
    await page.goto('/');
    await page.setInputFiles('#templateInput', SAMPLE_PATH);
    await expect(page.locator('#templatePreview')).toContainText(/puertos LAN/, { timeout: 5000 });
  });

  test('proceso completo: origen + plantilla -> output descargable', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
    page.on('console', (m) => { if (m.type() === 'error') errors.push(`console: ${m.text()}`); });

    await page.goto('/');
    // Cargar origen (80F)
    await page.setInputFiles('#fileInput', SAMPLE_PATH);
    // Cargar plantilla (tambien 80F como ejemplo rapido)
    await page.setInputFiles('#templateInput', SAMPLE_PATH);

    // Boton habilitado
    await expect(page.locator('#btnProcess')).toBeEnabled({ timeout: 5000 });

    // Procesar
    await page.click('#btnProcess');
    await expect(page.locator('#status')).toContainText('Procesado OK', { timeout: 30000 });
    await expect(page.locator('#btnDownload')).toBeEnabled();

    // Verificar output contiene interfaces clave
    await page.click('.tab[data-tab="output"]');
    const output = await page.locator('#outputLog').innerText();
    expect(output).toMatch(/config system interface/);
    expect(output).toMatch(/edit "claro"/);
    expect(output).toMatch(/accprofile "super_admin"/);

    expect(errors).toEqual([]);
  });

  test('boton Procesar deshabilitado hasta tener ambos backups', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#btnProcess')).toBeDisabled();

    // Solo origen
    await page.setInputFiles('#fileInput', SAMPLE_PATH);
    await expect(page.locator('#btnProcess')).toBeDisabled();

    // Ahora plantilla
    await page.setInputFiles('#templateInput', SAMPLE_PATH);
    await expect(page.locator('#btnProcess')).toBeEnabled();
  });

  test('descarga el .conf resultante', async ({ page }) => {
    await page.goto('/');
    await page.setInputFiles('#fileInput', SAMPLE_PATH);
    await page.setInputFiles('#templateInput', SAMPLE_PATH);
    await page.click('#btnProcess');
    await expect(page.locator('#status')).toContainText('Procesado OK', { timeout: 30000 });

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.click('#btnDownload'),
    ]);
    expect(download.suggestedFilename()).toMatch(/\.conf$/);
  });

  test('responsive mobile', async ({ page }) => {
    await page.setViewportSize({ width: 480, height: 900 });
    await page.goto('/');
    await expect(page.locator('#btnProcess')).toBeVisible();
    await expect(page.locator('#btnDownload')).toBeVisible();
  });
});

test.describe('API endpoints', () => {
  test('health', async ({ request }) => {
    const r = await request.get('/api/health');
    expect(r.ok()).toBe(true);
    const j = await r.json();
    expect(j.ok).toBe(true);
  });

  test('preview-template detecta 80F (6 internal + wan1/2)', async ({ request }) => {
    const fs = await import('fs/promises');
    const text = await fs.readFile(SAMPLE_PATH, 'utf-8');
    const r = await request.post('/api/preview-template', {
      data: { template: text },
    });
    expect(r.ok()).toBe(true);
    const j = await r.json();
    expect(j.ok).toBe(true);
    expect(j.model_hint).toBe('80F');
    expect(j.wan_count).toBe(2);
    expect(j.lan_count).toBeGreaterThanOrEqual(6);
    expect(Array.isArray(j.slots)).toBe(true);
  });

  test('preview-template sin texto devuelve 400', async ({ request }) => {
    const r = await request.post('/api/preview-template', { data: {} });
    expect(r.status()).toBe(400);
  });

  test('preview-template sin config system interface devuelve 400', async ({ request }) => {
    const r = await request.post('/api/preview-template', {
      data: { template: 'config system global\n    set hostname test\nend\n' },
    });
    expect(r.status()).toBe(400);
    const j = await r.json();
    expect(j.error).toMatch(/config system interface/);
  });

  test('process sin template devuelve 400', async ({ request }) => {
    const fs = await import('fs/promises');
    const text = await fs.readFile(SAMPLE_PATH, 'utf-8');
    const r = await request.post('/api/process', {
      data: { text },
    });
    expect(r.status()).toBe(400);
    const j = await r.json();
    expect(j.error).toMatch(/template/);
  });

  test('sample endpoint sirve Ejemplo_80F.conf', async ({ request }) => {
    const r = await request.get('/sample/Ejemplo_80F.conf');
    expect(r.ok()).toBe(true);
    const text = await r.text();
    expect(text).toContain('#config-version=FGT80F');
  });

  test('sample endpoint rechaza path traversal', async ({ request }) => {
    const r = await request.get('/sample/../app/main.py');
    expect(r.status()).toBeGreaterThanOrEqual(400);
  });
});