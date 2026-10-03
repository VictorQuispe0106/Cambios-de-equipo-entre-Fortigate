// Genera el .conf origen para tests
import { promises as fs } from 'fs';

const origen = [
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
  origen.push(`    edit "port${i}"`);
  origen.push('        set type physical');
  origen.push('    next');
}
origen.push('end');
origen.push('config system admin');
origen.push('    edit "admin"');
origen.push('        set password ENC dummy');
origen.push('    next');
origen.push('end');

const plantilla = [
  '#config-version=FGT80F-7.4.12',
  'config system interface',
  '    edit "wan1"',
  '        set type physical',
  '    next',
  '    edit "wan2"',
  '        set type physical',
  '    next',
];
for (let i = 1; i <= 6; i++) {
  plantilla.push(`    edit "port${i}"`);
  plantilla.push('        set type physical');
  plantilla.push('    next');
}
plantilla.push('end');
plantilla.push('config system admin');
plantilla.push('    edit "admin"');
plantilla.push('        set password ENC dummy');
plantilla.push('    next');
plantilla.push('end');

fs.writeFile('C:\\Users\\E758455\\AppData\\Local\\Temp\\origen_100f_4ports.conf', origen.join('\n') + '\n', 'utf-8');
fs.writeFile('C:\\Users\\E758455\\AppData\\Local\\Temp\\plantilla_80f_6ports.conf', plantilla.join('\n') + '\n', 'utf-8');
console.log('Archivos generados');