#!/usr/bin/env node

/**
 * Amprealize CLI Wrapper
 *
 * This npm package provides a cross-platform wrapper for the Amprealize Python CLI.
 * It automatically manages Python environment detection and falls back to direct
 * pip installation if needed.
 */

const { spawn, spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

const AMPREALIZE_VERSION = '0.1.0';
const PYTHON_MIN_VERSION = [3, 10];

/**
 * Find a suitable Python interpreter
 */
function findPython() {
  const candidates = process.platform === 'win32'
    ? ['python', 'python3', 'py -3']
    : ['python3', 'python'];

  for (const cmd of candidates) {
    try {
      const parts = cmd.split(' ');
      const result = spawnSync(parts[0], [...parts.slice(1), '--version'], {
        encoding: 'utf8',
        timeout: 5000,
      });

      if (result.status === 0 && result.stdout) {
        const match = result.stdout.match(/Python (\d+)\.(\d+)/);
        if (match) {
          const [, major, minor] = match.map(Number);
          if (major > PYTHON_MIN_VERSION[0] ||
              (major === PYTHON_MIN_VERSION[0] && minor >= PYTHON_MIN_VERSION[1])) {
            return cmd;
          }
        }
      }
    } catch {
      // Continue to next candidate
    }
  }
  return null;
}

/**
 * Check if amprealize is installed in Python
 */
function isAmprealizeInstalled(pythonCmd) {
  try {
    const parts = pythonCmd.split(' ');
    const result = spawnSync(parts[0], [...parts.slice(1), '-c', 'import amprealize'], {
      encoding: 'utf8',
      timeout: 10000,
    });
    return result.status === 0;
  } catch {
    return false;
  }
}

/**
 * Get the amprealize binary path
 */
function getAmprealizePath(pythonCmd) {
  try {
    const parts = pythonCmd.split(' ');
    const result = spawnSync(parts[0], [
      ...parts.slice(1),
      '-c',
      'import shutil; print(shutil.which("amprealize") or "")'
    ], {
      encoding: 'utf8',
      timeout: 5000,
    });

    if (result.status === 0 && result.stdout.trim()) {
      return result.stdout.trim();
    }
  } catch {
    // Fall through
  }

  // Check common locations
  const homeDir = os.homedir();
  const locations = process.platform === 'win32'
    ? [
        path.join(homeDir, 'AppData', 'Local', 'Programs', 'Python', 'Python311', 'Scripts', 'amprealize.exe'),
        path.join(homeDir, 'AppData', 'Roaming', 'Python', 'Python311', 'Scripts', 'amprealize.exe'),
      ]
    : [
        path.join(homeDir, '.local', 'bin', 'amprealize'),
        '/usr/local/bin/amprealize',
        '/opt/homebrew/bin/amprealize',
      ];

  for (const loc of locations) {
    if (fs.existsSync(loc)) {
      return loc;
    }
  }

  return null;
}

/**
 * Main entry point
 */
async function main() {
  const args = process.argv.slice(2);

  // Handle --npm-wrapper-version
  if (args.includes('--npm-wrapper-version')) {
    console.log(`amprealize npm wrapper v${AMPREALIZE_VERSION}`);
    process.exit(0);
  }

  // Find Python
  const pythonCmd = findPython();
  if (!pythonCmd) {
    console.error('Error: Python 3.10+ is required but not found.');
    console.error('');
    console.error('Install Python from:');
    console.error('  - macOS: brew install python@3.11');
    console.error('  - Ubuntu: sudo apt install python3.11');
    console.error('  - Windows: https://www.python.org/downloads/');
    process.exit(1);
  }

  // Check if amprealize is installed
  if (!isAmprealizeInstalled(pythonCmd)) {
    console.error('Amprealize Python package not found. Installing...');
    const parts = pythonCmd.split(' ');
    const installResult = spawnSync(parts[0], [
      ...parts.slice(1),
      '-m', 'pip', 'install', '--user', 'amprealize'
    ], {
      stdio: 'inherit',
      timeout: 120000,
    });

    if (installResult.status !== 0) {
      console.error('Failed to install amprealize. Please run manually:');
      console.error(`  ${pythonCmd} -m pip install amprealize`);
      process.exit(1);
    }
  }

  // Find amprealize binary
  const amprealizePath = getAmprealizePath(pythonCmd);
  if (!amprealizePath) {
    // Fall back to running as Python module
    const parts = pythonCmd.split(' ');
    const proc = spawn(parts[0], [...parts.slice(1), '-m', 'amprealize.cli', ...args], {
      stdio: 'inherit',
    });

    proc.on('close', (code) => {
      process.exit(code || 0);
    });
    return;
  }

  // Run amprealize
  const proc = spawn(amprealizePath, args, {
    stdio: 'inherit',
  });

  proc.on('close', (code) => {
    process.exit(code || 0);
  });
}

main().catch((err) => {
  console.error('Error:', err.message);
  process.exit(1);
});
