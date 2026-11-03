#!/usr/bin/env node
/**
 * Builds the dashboard and, unless --no-start is passed, starts the preview
 * server. This is what makes `npm run build` both compile and launch the app.
 */
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dashboardDir = path.join(rootDir, 'artifacts', 'gcp-finops-dashboard');
const shouldStart = !process.argv.includes('--no-start');
const npmCommand = process.platform === 'win32' ? 'npm.cmd' : 'npm';

const port = process.env.PORT ?? '5173';
const basePath = process.env.BASE_PATH ?? '/';
const env = { ...process.env, PORT: port, BASE_PATH: basePath };

function runNpmScript(script) {
  return new Promise((resolve, reject) => {
    const child = spawn(npmCommand, ['run', script], {
      cwd: dashboardDir,
      env,
      stdio: 'inherit',
    });

    child.on('error', reject);
    child.on('exit', (code, signal) => {
      if (signal) {
        process.kill(process.pid, signal);
        return;
      }
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`"npm run ${script}" exited with code ${code}`));
      }
    });
  });
}

try {
  console.log('› Compilando o dashboard...');
  await runNpmScript('build');

  if (!shouldStart) {
    console.log('✓ Build concluído.');
    process.exit(0);
  }

  console.log(`› Iniciando o app (porta padrão ${port})...`);
  await runNpmScript('serve');
} catch (error) {
  console.error(`✗ ${error.message}`);
  process.exit(1);
}
