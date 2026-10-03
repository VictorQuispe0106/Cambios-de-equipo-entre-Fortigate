import { test } from '@playwright/test';
import path from 'path';

const SAMPLE_80F = 'C:\\Users\\E758455\\Desktop\\Opencode-proyects\\CAMBIO DE EQUIPO AUTOMATIZACION\\Ejemplo_80F.conf';
const SAMPLE_60F = 'C:\\Users\\E758455\\Desktop\\Opencode-proyects\\CAMBIO DE EQUIPO AUTOMATIZACION\\Ejemplo_60F.conf';
const SAMPLE_100F = 'C:\\Users\\E758455\\Desktop\\Opencode-proyects\\CAMBIO DE EQUIPO AUTOMATIZACION\\Ejemplo_100F.conf';

test('validar que se muestran TODOS los excedentes', async ({ page }) => {
  await page.setViewportSize({ width: 1400, height: 1000 });
  const outDir = path.join(__dirname, '..', 'screenshots');

  await page.goto('/');
  await page.waitForLoadState('networkidle');

  // 80F como origen
  await page.setInputFiles('#fileInput', SAMPLE_80F);
  await page.waitForTimeout(300);

  // 60F como destino (caso donde hay 4 excedentes todos sin slot propuesto)
  await page.setInputFiles('#templateInput', SAMPLE_60F);
  await page.waitForFunction(() => {
    const sec = document.querySelector('#reassignSection');
    return sec && !sec.classList.contains('hidden');
  }, undefined, { timeout: 8000 });
  await page.waitForTimeout(500);

  // Contar excedentes visibles
  const rows1 = await page.locator('.reassign-row').count();
  console.log(`80F -> 60F: ${rows1} excedentes visibles`);

  await page.screenshot({ path: path.join(outDir, 'reassign-80F-a-60F.png'), fullPage: true });

  // Cambiar a 100F como destino (caso donde algunas reasignaciones son automaticas)
  await page.setInputFiles('#templateInput', SAMPLE_100F);
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outDir, 'reassign-80F-a-100F.png'), fullPage: true });
});