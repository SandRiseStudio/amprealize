#!/usr/bin/env node

/**
 * Amprealize npm postinstall script
 *
 * Checks for Python availability and optionally installs the Python package.
 */

const { spawnSync } = require('child_process');

const PYTHON_MIN_VERSION = [3, 10];

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
            return { cmd, version: `${major}.${minor}` };
          }
        }
      }
    } catch {
      // Continue
    }
  }
  return null;
}

function main() {
  console.log('');
  console.log('╭──────────────────────────────────────────────────────────╮');
  console.log('│                  Amprealize CLI                          │');
  console.log('╰──────────────────────────────────────────────────────────╯');
  console.log('');

  const python = findPython();

  if (python) {
    console.log(`✓ Python ${python.version} found (${python.cmd})`);
    console.log('');
    console.log('The Amprealize Python package will be installed automatically');
    console.log('when you first run the `amprealize` command.');
    console.log('');
    console.log('Or install it now:');
    console.log(`  ${python.cmd} -m pip install amprealize`);
  } else {
    console.log('⚠ Python 3.10+ not found');
    console.log('');
    console.log('Amprealize requires Python 3.10 or later. Install it from:');
    console.log('');
    if (process.platform === 'darwin') {
      console.log('  brew install python@3.11');
    } else if (process.platform === 'linux') {
      console.log('  Ubuntu/Debian: sudo apt install python3.11');
      console.log('  Fedora:        sudo dnf install python3.11');
      console.log('  Arch:          sudo pacman -S python');
    } else if (process.platform === 'win32') {
      console.log('  https://www.python.org/downloads/');
      console.log('  Or: winget install Python.Python.3.11');
    }
    console.log('');
    console.log('Then run: pip install amprealize');
  }

  console.log('');
  console.log('Quick start:');
  console.log('  amprealize init        # Initialize a new project');
  console.log('  amprealize doctor      # Check installation health');
  console.log('  amprealize mcp-server  # Start the MCP server');
  console.log('');
}

main();
