import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { sleep } from './helpers.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const workerRoot = path.resolve(__dirname, '..', '..');
const extensionDir = path.join(workerRoot, 'extension');

function attachLogs(proc, prefix, onStderrLine = null) {
  proc.stdout.on('data', (chunk) => process.stdout.write(`[${prefix}] ${chunk}`));
  proc.stderr.on('data', (chunk) => {
    const text = chunk.toString();
    process.stderr.write(`[${prefix}] ${text}`);
    if (onStderrLine) {
      onStderrLine(text);
    }
  });
}

export function launchVirtualDisplay() {
  let launchError = null;
  const proc = spawn('Xvfb', [':99', '-screen', '0', '1360x900x24', '-nolisten', 'tcp'], {
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  proc.on('error', (err) => {
    launchError = String(err?.message || err);
  });
  proc.__launchError = () => launchError;
  attachLogs(proc, 'xvfb');
  return proc;
}

export function launchChromium({ browserBinary, showUi, noSandbox = false }) {
  const display = process.env.DISPLAY || '';
  if (showUi && !display) {
    throw new Error('BROWSER_PARSER_SHOW_UI=true requires DISPLAY to be set');
  }

  const userDataDir = '/tmp/browser-parser-profile';
  const args = [
    `--user-data-dir=${userDataDir}`,
    `--disable-extensions-except=${extensionDir}`,
    `--load-extension=${extensionDir}`,
    '--no-first-run',
    '--disable-default-apps',
    '--disable-popup-blocking',
    '--disable-setuid-sandbox',
    '--disable-dev-shm-usage',
    '--disable-gpu',
    '--use-gl=swiftshader',
    '--disable-vulkan',
    '--disable-features=Vulkan',
    '--disable-features=UseDBus,CalculateNativeWinOcclusion',
    '--disable-blink-features=AutomationControlled',
    '--test-type',
    '--new-window',
    'about:blank',
  ];

  const disableSandboxFromEnv = String(process.env.BROWSER_PARSER_DISABLE_SANDBOX || 'false').toLowerCase() === 'true';
  if (noSandbox || disableSandboxFromEnv) {
    args.push('--no-sandbox');
  }

  let sawSandboxPermissionError = false;
  let didExit = false;
  let exitCode = null;
  let launchError = null;
  const proc = spawn(browserBinary, args, {
    stdio: ['ignore', 'pipe', 'pipe'],
    env: process.env,
  });
  proc.on('error', (err) => {
    launchError = String(err?.message || err);
  });
  proc.on('exit', (code) => {
    didExit = true;
    exitCode = code;
  });
  attachLogs(proc, 'chromium', (line) => {
    if (line.includes('sandbox/linux/services/credentials.cc') && line.includes('Permission denied')) {
      sawSandboxPermissionError = true;
    }
  });
  proc.__sawSandboxPermissionError = () => sawSandboxPermissionError;
  proc.__didExit = () => didExit;
  proc.__exitCode = () => exitCode;
  proc.__launchError = () => launchError;
  return proc;
}

export async function startBrowserEnvironment({ browserBinary, showUi }) {
  let xvfbProc = null;
  if (!showUi) {
    xvfbProc = launchVirtualDisplay();
    process.env.DISPLAY = ':99';
    await sleep(1200);
  }

  const disableSandboxFromEnv = String(process.env.BROWSER_PARSER_DISABLE_SANDBOX || 'false').toLowerCase() === 'true';
  const runningInDocker = existsSync('/.dockerenv');
  const startWithNoSandbox = disableSandboxFromEnv || runningInDocker;

  let chromiumProc = launchChromium({ browserBinary, showUi, noSandbox: startWithNoSandbox });
  // Give Chromium a short warm-up window and watch for early sandbox crash.
  for (let i = 0; i < 15; i += 1) {
    await sleep(180);
    if (typeof chromiumProc.__launchError === 'function' && chromiumProc.__launchError()) {
      break;
    }
    if (typeof chromiumProc.__sawSandboxPermissionError === 'function' && chromiumProc.__sawSandboxPermissionError()) {
      break;
    }
    if (typeof chromiumProc.__didExit === 'function' && chromiumProc.__didExit()) {
      break;
    }
  }

  if (
    (typeof chromiumProc.__launchError === 'function' && chromiumProc.__launchError())
  ) {
    throw new Error(`Chromium launch failed: ${chromiumProc.__launchError()}`);
  }

  if (
    !startWithNoSandbox && (
    (typeof chromiumProc.__sawSandboxPermissionError === 'function' && chromiumProc.__sawSandboxPermissionError()) ||
    (typeof chromiumProc.__didExit === 'function' && chromiumProc.__didExit())
    )
  ) {
    console.log('[chromium] early browser failure detected; restarting with --no-sandbox fallback');
    try {
      chromiumProc.kill('SIGTERM');
    } catch {
      // ignore
    }
    chromiumProc = launchChromium({ browserBinary, showUi, noSandbox: true });
    await sleep(1200);
  }

  return {
    chromiumProc,
    xvfbProc,
    stop: async () => {
      try {
        chromiumProc.kill('SIGTERM');
      } catch {
        // ignore
      }
      if (xvfbProc) {
        try {
          xvfbProc.kill('SIGTERM');
        } catch {
          // ignore
        }
      }
    },
  };
}
