import { test } from '@playwright/test';
import path from 'path';

const SAMPLE_PATH = 'C:\\Users\\E758455\\Desktop\\Opencode-proyects\\CAMBIO DE EQUIPO AUTOMATIZACION\\Ejemplo_80F.conf';

test('captura screenshots para revision visual', async ({ page }) => {
  await page.setViewportSize({ width: 1400, height: 1000 });
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  const outDir = path.join(__dirname, '..', 'screenshots');
  await page.screenshot({ path: path.join(outDir, '01-inicial.png'), fullPage: true });

  // Cargar origen
  await page.setInputFiles('#fileInput', SAMPLE_PATH);
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outDir, '02-origen-cargado.png'), fullPage: true });

  // Cargar plantilla
  await page.setInputFiles('#templateInput', SAMPLE_PATH);
  await page.waitForFunction(() => {
    const preview = document.querySelector('#templatePreview');
    return preview && !preview.classList.contains('empty') && preview.textContent.includes('puertos LAN');
  }, undefined, { timeout: 10000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outDir, '03-plantilla-detectada.png'), fullPage: true });

  // Procesar
  await page.click('#btnProcess');
  await page.waitForSelector('#status:has-text("Procesado OK")', { timeout: 30000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outDir, '04-procesado-mapeo.png'), fullPage: true });

  await page.click('.tab[data-tab="diff"]');
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outDir, '05-diff.png'), fullPage: true });

  await page.click('.tab[data-tab="output"]');
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outDir, '06-output.png'), fullPage: true });

  await page.click('.tab[data-tab="warnings"]');
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outDir, '07-warnings.png'), fullPage: true });

  // Hover sobre el boton Procesar
  await page.click('.tab[data-tab="mapping"]');
  await page.hover('#btnProcess');
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(outDir, '08-hover-button.png'), fullPage: false });
});