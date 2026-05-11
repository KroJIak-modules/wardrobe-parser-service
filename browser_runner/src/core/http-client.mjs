export async function fetchTextWithRetries(url, maxRetries = 5) {
  let lastError = 'unknown';
  for (let attempt = 1; attempt <= maxRetries; attempt += 1) {
    try {
      const response = await fetch(url, { method: 'GET', redirect: 'follow', cache: 'no-store' });
      if (response.status === 429 || response.status >= 500) {
        if (attempt < maxRetries) {
          await sleep(Math.min(2 ** attempt * 600, 12000));
          continue;
        }
      }
      if (!response.ok) return { ok: false, status: response.status, error: `HTTP_${response.status}` };
      return { ok: true, status: response.status, body: await response.text() };
    } catch (err) {
      lastError = String(err?.message || err);
      if (attempt < maxRetries) {
        await sleep(Math.min(2 ** attempt * 600, 12000));
      }
    }
  }
  return { ok: false, status: null, error: lastError };
}

export async function fetchJsonWithRetries(url, maxRetries = 5) {
  const res = await fetchTextWithRetries(url, maxRetries);
  if (!res.ok) return res;
  try {
    return { ok: true, status: res.status, body: JSON.parse(res.body) };
  } catch {
    return { ok: false, status: res.status, error: 'invalid_json' };
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
