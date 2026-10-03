import { test } from '@playwright/test';
import path from 'path';

const SAMPLE_80F = 'C:\\Users\\E758455\\Desktop\\Opencode-proyects\\CAMBIO DE EQUIPO AUTOMATIZACION\\Ejemplo_80F.conf';
const SAMPLE_60F = 'C:\\Users\\E758455\\Desktop\\Opencode-proyects\\CAMBIO DE EQUIPO AUTOMATIZACION\\Ejemplo_60F.conf';
const SAMPLE_100F = 'C:\\Users\\E758455\\Desktop\\Opencode-proyects\\CAMBIO DE EQUIPO AUTOMATIZACION\\Ejemplo_100F.conf';

test('captura screenshots del flujo completo', async ({ page }) => {
  await page.setViewportSize({ width: 1400, height: 1000 });
  const outDir = path.join(__dirname, '..', 'screenshots');

  await page.goto('/');
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: path.join(outDir, '01-inicial.png'), fullPage: true });

  // Cargar origen
  await page.setInputFiles('#fileInput', SAMPLE_80F);
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outDir, '02-origen.png'), fullPage: true });

  // Cargar plantilla 60F (con excedentes)
  await page.setInputFiles('#templateInput', SAMPLE_60F);
  await page.waitForFunction(() => {
    const preview = document.querySelector('#templatePreview');
    return preview && !preview.classList.contains('empty') && preview.textContent.includes('puertos LAN');
  }, undefined, { timeout: 10000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outDir, '03-plantilla-60F.png'), fullPage: true });

  // Cargar plantilla 100F (sin excedentes)
  await page.setInputFiles('#templateInput', SAMPLE_100F);
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outDir, '04-plantilla-100F-sin-excedentes.png'), fullPage: true });

  // Volver a 60F para ver excedentes
  await page.setInputFiles('#templateInput', SAMPLE_60F);
  await page.waitForFunction(() => {
    const sec = document.querySelector('#reassignSection');
    return sec && !sec.classList.contains('hidden');
  }, undefined, { timeout: 5000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outDir, '05-excedentes-dropdown.png'), fullPage: true });

  // Seleccionar manualmente un slot para 'a'
  const firstSelect = page.locator('.reassign-select').first();
  await firstSelect.selectOption({ index: 3 });  // seleccionar port1
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(outDir, '06-asignacion-manual.png'), fullPage: true });

  // Seleccionar para todos
  const selects = page.locator('.reassign-select');
  const total = await selects.count();
  for (let i = 0; i < total; i++) {
    const opts = await selects.nth(i).locator('option').count();
    if (opts > 1 + i) {  // evitar duplicados en el mismo slot
      await selects.nth(i).selectOption({ index: 1 + (i % 4) });
    }
  }
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(outDir, '07-todos-asignados.png'), fullPage: true });

  // Procesar
  await page.click('#btnProcess');
  await page.waitForSelector('#status:has-text("Procesado OK")', { timeout: 30000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outDir, '08-resultado.png'), fullPage: true });

  // Tab Diff
  await page.click('.tab[data-tab="diff"]');
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outDir, '09-diff.png'), fullPage: true });

  // Tab Output
  await page.click('.tab[data-tab="output"]');
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outDir, '10-output.png'), fullPage: true });
});