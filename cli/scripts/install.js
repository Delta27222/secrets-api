const { execSync } = require('child_process');

function runCommand(cmd) {
  try {
    execSync(cmd, { stdio: 'inherit' });
    return true;
  } catch {
    return false;
  }
}

// Detecta pip
const success =
  runCommand('python3 -m pip install -e .') ||
  runCommand('python -m pip install -e .');

if (!success) {
  console.error(`
  Error: No se encontró pip instalado.
  Soluciones:
  1. Ejecuta: python3 -m ensurepip
  2. O instala pip manualmente: https://pip.pypa.io/en/stable/installation/
  `);
  process.exit(1);
}
