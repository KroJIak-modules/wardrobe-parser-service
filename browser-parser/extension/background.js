const WS_URL = 'ws://127.0.0.1:8777';
let socket = null;
let reconnectTimer = null;
let connecting = false;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function getActiveTabId() {
  const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (tabs.length > 0 && tabs[0].id !== undefined) {
    return tabs[0].id;
  }
  const all = await chrome.tabs.query({});
  const first = all.find((tab) => tab.id !== undefined);
  return first ? first.id : null;
}

async function runInTab(func, args = []) {
  const tabId = await getActiveTabId();
  if (tabId === null) {
    throw new Error('No active tab found');
  }
  const res = await chrome.scripting.executeScript({
    target: { tabId },
    func,
    args,
  });
  return res?.[0]?.result;
}

async function highlightSelector(selector, color) {
  return runInTab(
    (sel, c) => {
      const el = document.querySelector(sel);
      if (!el) return { ok: false, error: 'selector_not_found' };
      const r = el.getBoundingClientRect();
      const box = document.createElement('div');
      box.style.position = 'fixed';
      box.style.left = `${r.left}px`;
      box.style.top = `${r.top}px`;
      box.style.width = `${r.width}px`;
      box.style.height = `${r.height}px`;
      box.style.border = `3px solid ${c}`;
      box.style.background = 'transparent';
      box.style.zIndex = '2147483646';
      box.style.pointerEvents = 'none';
      box.style.borderRadius = '6px';
      document.body.appendChild(box);
      setTimeout(() => box.remove(), 900);
      return { ok: true, rect: { x: r.x, y: r.y, width: r.width, height: r.height } };
    },
    [selector, color],
  );
}

async function clickSelector(selector) {
  return runInTab(
    (sel) => {
      const el = document.querySelector(sel);
      if (!el) return { ok: false, error: 'selector_not_found' };
      el.click();
      return { ok: true };
    },
    [selector],
  );
}

async function readSelector(selector) {
  return runInTab(
    (sel) => {
      const el = document.querySelector(sel);
      if (!el) return { ok: false, error: 'selector_not_found' };
      return {
        ok: true,
        text: (el.textContent || '').trim(),
        html: (el.innerHTML || '').trim().slice(0, 5000),
      };
    },
    [selector],
  );
}

async function collectLinks(selector, limit = 500) {
  return runInTab(
    (sel, maxCount) => {
      const anchors = Array.from(document.querySelectorAll(sel));
      const links = [];
      for (const a of anchors) {
        if (!(a instanceof HTMLAnchorElement)) continue;
        if (!a.href) continue;
        links.push(a.href);
        if (links.length >= maxCount) break;
      }
      return { ok: true, links };
    },
    [selector, limit],
  );
}

async function getPageMeta() {
  return runInTab(() => {
    return {
      ok: true,
      url: window.location.href,
      title: document.title || '',
      readyState: document.readyState,
    };
  });
}

async function renderStatusOverlay(text, tone = 'info') {
  return runInTab(
    (value, kind) => {
      const id = '__browser_parser_status_overlay__';
      let el = document.getElementById(id);
      if (!el) {
        el = document.createElement('div');
        el.id = id;
        el.style.position = 'fixed';
        el.style.right = '14px';
        el.style.bottom = '14px';
        el.style.maxWidth = '40vw';
        el.style.padding = '10px 12px';
        el.style.borderRadius = '10px';
        el.style.boxShadow = '0 10px 30px rgba(0,0,0,0.28)';
        el.style.zIndex = '2147483647';
        el.style.fontFamily = 'ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial';
        el.style.fontSize = '13px';
        el.style.lineHeight = '1.35';
        el.style.fontWeight = '600';
        el.style.pointerEvents = 'none';
        document.body.appendChild(el);
      }
      const toneStyles = {
        info: { bg: 'rgba(17,24,39,0.92)', fg: '#e5e7eb', border: '1px solid rgba(229,231,235,0.18)' },
        success: { bg: 'rgba(6,78,59,0.92)', fg: '#d1fae5', border: '1px solid rgba(110,231,183,0.35)' },
        warn: { bg: 'rgba(120,53,15,0.92)', fg: '#fef3c7', border: '1px solid rgba(245,158,11,0.35)' },
        error: { bg: 'rgba(127,29,29,0.92)', fg: '#fee2e2', border: '1px solid rgba(248,113,113,0.35)' },
      };
      const style = toneStyles[kind] || toneStyles.info;
      el.style.background = style.bg;
      el.style.color = style.fg;
      el.style.border = style.border;
      el.textContent = `[Browser Parser] ${String(value || '')}`;
      return { ok: true };
    },
    [text, tone],
  );
}

async function fetchWithRetries(url, parseJson = false, maxRetries = 5) {
  let lastError = null;
  for (let attempt = 1; attempt <= maxRetries; attempt += 1) {
    try {
      const response = await fetch(url, {
        method: 'GET',
        credentials: 'include',
        redirect: 'follow',
        cache: 'no-store',
      });
      if (response.status === 429 || response.status >= 500) {
        if (attempt < maxRetries) {
          const retryAfter = response.headers.get('Retry-After');
          const base = retryAfter && /^\d+$/.test(retryAfter) ? Number(retryAfter) * 1000 : Math.min(2 ** attempt * 700, 20000);
          await sleep(base + Math.floor(Math.random() * 700));
          continue;
        }
      }
      if (!response.ok) {
        return { ok: false, status: response.status, error: `HTTP_${response.status}` };
      }
      if (parseJson) {
        return { ok: true, status: response.status, body: await response.json() };
      }
      return { ok: true, status: response.status, body: await response.text() };
    } catch (err) {
      lastError = String(err?.message || err);
      if (attempt < maxRetries) {
        await sleep(Math.min(2 ** attempt * 600, 12000));
        continue;
      }
    }
  }
  return { ok: false, status: null, error: lastError || 'fetch_failed' };
}

async function handleCommand(command) {
  const { action } = command;
  if (action === 'ping') {
    return { ok: true, pong: true, ts: Date.now() };
  }
  if (action === 'navigate') {
    const tabId = await getActiveTabId();
    if (tabId === null) return { ok: false, error: 'no_tab' };
    await chrome.tabs.update(tabId, { url: command.url });
    return { ok: true };
  }
  if (action === 'fetch_text') {
    return fetchWithRetries(command.url, false, command.max_retries || 5);
  }
  if (action === 'fetch_json') {
    return fetchWithRetries(command.url, true, command.max_retries || 5);
  }
  if (action === 'highlight_read') {
    const hi = await highlightSelector(command.selector, '#22c55e');
    if (!hi?.ok) return hi;
    const read = await readSelector(command.selector);
    return read;
  }
  if (action === 'highlight_click') {
    const hi = await highlightSelector(command.selector, '#ef4444');
    if (!hi?.ok) return hi;
    return clickSelector(command.selector);
  }
  if (action === 'collect_links') {
    return collectLinks(command.selector || 'a[href]', command.limit || 500);
  }
  if (action === 'get_page_meta') {
    return getPageMeta();
  }
  if (action === 'status_overlay') {
    return renderStatusOverlay(command.text || '', command.tone || 'info');
  }
  return { ok: false, error: `unknown_action:${action}` };
}

function send(obj) {
  if (!socket || socket.readyState !== WebSocket.OPEN) return;
  socket.send(JSON.stringify(obj));
}

function connect() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }
  if (connecting) {
    return;
  }
  connecting = true;
  try {
    socket = new WebSocket(WS_URL);
  } catch (err) {
    connecting = false;
    scheduleReconnect();
    return;
  }

  socket.addEventListener('open', () => {
    connecting = false;
    send({ type: 'hello', source: 'extension', extensionId: chrome.runtime.id, ts: Date.now() });
  });

  socket.addEventListener('message', async (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      return;
    }
    if (!message || message.type !== 'command' || !message.id) return;
    try {
      const result = await handleCommand(message);
      send({ type: 'response', id: message.id, ok: true, result });
    } catch (err) {
      send({ type: 'response', id: message.id, ok: false, error: String(err?.message || err) });
    }
  });

  socket.addEventListener('close', () => {
    connecting = false;
    socket = null;
    scheduleReconnect();
  });

  socket.addEventListener('error', () => {
    connecting = false;
    try {
      socket.close();
    } catch (_) {
      // ignore
    }
  });
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, 1500);
}

chrome.runtime.onStartup.addListener(() => connect());
chrome.runtime.onInstalled.addListener(() => connect());
connect();
