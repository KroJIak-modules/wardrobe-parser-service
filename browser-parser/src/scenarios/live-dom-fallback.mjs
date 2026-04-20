import { sleep } from '../core/helpers.mjs';

function logLive(message) {
  console.log(`[scenario:live] ${message}`);
}

async function setOverlay(bridge, text, tone = 'info') {
  try {
    await bridge.send('status_overlay', { text, tone }, 15000);
  } catch {
    // non-blocking helper
  }
}

function normalizeProductUrl(url, baseUrl) {
  try {
    const u = new URL(url, baseUrl);
    if (!u.pathname.includes('/products/')) return '';
    u.search = '';
    u.hash = '';
    return u.toString().replace(/\/$/, '');
  } catch {
    return '';
  }
}

function handleFromProductUrl(url) {
  const marker = '/products/';
  const idx = url.indexOf(marker);
  if (idx < 0) return '';
  return url.slice(idx + marker.length).split('?')[0].replace(/\/$/, '');
}

export async function runLiveDomFallback({ bridge, baseUrl, options }) {
  const maxPages = Number(options.maxCollectionPages || 12);
  const jsSampleSize = Number(options.jsSampleSize || 80);
  const startedAt = new Date().toISOString();

  const result = {
    mode: 'live_dom_fallback',
    started_at: startedAt,
    pages_visited: 0,
    unique_product_urls: 0,
    js_sample_size: 0,
    js_sample_success: 0,
    js_sample_failed: 0,
    js_sample_429: 0,
    errors: [],
    notes: [],
    product_urls: [],
  };

  await setOverlay(bridge, 'Fallback: живой обход страниц коллекции...');

  const found = new Set();
  for (let page = 1; page <= maxPages; page += 1) {
    const pageUrl = `${baseUrl}/collections/all?page=${page}`;
    logLive(`navigate page ${page}/${maxPages}: ${pageUrl}`);
    await setOverlay(bridge, `Fallback: страница коллекции ${page}/${maxPages}`);
    await bridge.send('navigate', { url: pageUrl }, 45000);
    await sleep(2200);

    result.pages_visited += 1;
    try {
      const meta = await bridge.send('get_page_meta', {}, 15000);
      logLive(`page meta: ${meta?.url || 'unknown'}`);
    } catch {
      // ignore
    }

    try {
      await bridge.send('highlight_read', { selector: 'body' }, 15000);
    } catch {
      // ignore
    }

    let links = [];
    try {
      const res = await bridge.send(
        'collect_links',
        { selector: 'a[href*="/products/"]', limit: 2500 },
        45000,
      );
      links = Array.isArray(res?.links) ? res.links : [];
    } catch (err) {
      result.errors.push(`collect links failed page=${page}: ${String(err?.message || err)}`);
      continue;
    }

    const before = found.size;
    for (const raw of links) {
      const normalized = normalizeProductUrl(raw, baseUrl);
      if (normalized) found.add(normalized);
    }
    const added = found.size - before;
    logLive(`page ${page} links=${links.length} added=${added} total=${found.size}`);

    if (page >= 2 && added === 0) {
      result.notes.push(`early stop: no new product links on page ${page}`);
      break;
    }
  }

  result.unique_product_urls = found.size;
  result.product_urls = [...found];
  await setOverlay(bridge, `Fallback: собрано URL товаров ${result.unique_product_urls}`);

  const sample = result.product_urls.slice(0, jsSampleSize);
  result.js_sample_size = sample.length;
  for (let i = 0; i < sample.length; i += 1) {
    if (i % 10 === 0 || i === sample.length - 1) {
      await setOverlay(bridge, `Fallback: проверка products.js ${i + 1}/${sample.length}`);
    }
    const handle = handleFromProductUrl(sample[i]);
    if (!handle) {
      result.js_sample_failed += 1;
      continue;
    }
    try {
      const res = await bridge.send('fetch_json', {
        url: `${baseUrl}/products/${handle}.js`,
        max_retries: 2,
      }, 120000);
      if (res?.ok && res?.body && (res.body.id || res.body.handle)) {
        result.js_sample_success += 1;
      } else {
        if (res?.status === 429 || res?.error === 'HTTP_429') {
          result.js_sample_429 += 1;
        }
        result.js_sample_failed += 1;
      }
    } catch (err) {
      if (String(err?.message || err).includes('429')) {
        result.js_sample_429 += 1;
      }
      result.js_sample_failed += 1;
    }
  }

  await setOverlay(
    bridge,
    `Fallback готов: URL=${result.unique_product_urls}, js ok=${result.js_sample_success}, fail=${result.js_sample_failed}`,
    'success',
  );
  result.finished_at = new Date().toISOString();
  return result;
}

