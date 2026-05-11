import { WebSocketServer } from 'ws';
import { sleep } from './helpers.mjs';

export class ExtensionBridge {
  constructor(port) {
    this.wss = new WebSocketServer({ host: '0.0.0.0', port });
    this.client = null;
    this.pending = new Map();
    this.seq = 0;

    this.wss.on('connection', (ws) => {
      this.client = ws;
      console.log('[bridge] extension connected');
      ws.on('message', (raw) => this.#onMessage(raw.toString()));
      ws.on('close', () => {
        if (this.client === ws) {
          this.client = null;
          console.log('[bridge] extension disconnected');
        }
      });
    });
  }

  #onMessage(raw) {
    let msg;
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }
    if (msg?.type !== 'response' || !msg.id) {
      return;
    }
    const pending = this.pending.get(msg.id);
    if (!pending) return;
    this.pending.delete(msg.id);
    if (msg.ok) {
      pending.resolve(msg.result);
    } else {
      pending.reject(new Error(msg.error || 'unknown_error'));
    }
  }

  async waitForConnection(timeoutMs = 60000) {
    const started = Date.now();
    while (!this.client) {
      if (Date.now() - started > timeoutMs) {
        throw new Error('Extension did not connect in time');
      }
      await sleep(250);
    }
  }

  async send(action, payload = {}, timeoutMs = 90000) {
    if (!this.client || this.client.readyState !== 1) {
      await this.waitForConnection(10000);
    }
    if (!this.client || this.client.readyState !== 1) {
      throw new Error('Extension socket is not connected');
    }

    const id = `cmd-${Date.now()}-${++this.seq}`;
    const message = { type: 'command', id, action, ...payload };

    const waiter = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Command timeout: ${action}`));
      }, timeoutMs);
      this.pending.set(id, {
        resolve: (value) => {
          clearTimeout(timer);
          resolve(value);
        },
        reject: (error) => {
          clearTimeout(timer);
          reject(error);
        },
      });
    });

    this.client.send(JSON.stringify(message));
    return waiter;
  }

  async close() {
    for (const [, pending] of this.pending) {
      pending.reject(new Error('bridge_closed'));
    }
    this.pending.clear();
    await new Promise((resolve) => this.wss.close(resolve));
  }

  isConnected() {
    return !!this.client && this.client.readyState === 1;
  }
}
