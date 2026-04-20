import { XMLParser } from 'fast-xml-parser';
import { sleep, toArray } from '../core/helpers.mjs';
import { runLiveDomFallback } from './live-dom-fallback.mjs';

const xmlParser = new XMLParser({ ignoreAttributes: false, trimValues: true });

function parseSitemapIndex(xmlText) {
  try {
    const parsed = xmlParser.parse(xmlText);
    const nodes = toArray(parsed?.sitemapindex?.sitemap);
    return nodes
      .map((n) => (typeof n?.loc === 'string' ? n.loc.trim() : ''))
      .filter(Boolean)
      .filter((u) => u.includes('sitemap_products_'));
  } catch {
    return [];
  }
}

function parseProductUrls(xmlText) {
  try {
    const parsed = xmlParser.parse(xmlText);
    const nodes = toArray(parsed?.urlset?.url);
    return nodes
      .map((n) => (typeof n?.loc === 'string' ? n.loc.trim() : ''))
      .filter((u) => u.includes('/products/'));
  } catch {
    return [];
  }
}

function handleFromProductUrl(url) {
  const marker = '/products/';
  const idx = url.indexOf(marker);
  if (idx < 0) return '';
  return url.slice(idx + marker.length).split('?')[0].replace(/\/$/, '');
}

function normalizeProductUrl(rawUrl, baseUrl) {
  try {
    const u = new URL(rawUrl, baseUrl);
    if (!u.pathname.includes('/products/')) return '';
    u.search = '';
    u.hash = '';
    u.pathname = u.pathname.replace(/^\/[a-z]{2}(?:-[a-z]{2})?(?=\/products\/)/i, '');
    return u.toString().replace(/\/$/, '');
  } catch {
    return '';
  }
}

function mapProductForExport(product, sourceUrl, currencyCode = null) {
  const payloadCurrencyRaw = String(product?.currency || product?.currency_code || '').trim().toUpperCase();
  const payloadCurrency = payloadCurrencyRaw.length === 3 ? payloadCurrencyRaw : null;
  const effectiveCurrency = payloadCurrency || currencyCode || null;
  const variants = Array.isArray(product?.variants) ? product.variants : [];
  const images = Array.isArray(product?.images) ? product.images : [];
  const normalizedPriceHints = [];

  const normalizeJsPriceIfNeeded = (value) => {
    if (value === null || value === undefined || value === '') return null;
    const n = Number(value);
    if (!Number.isFinite(n)) return null;
    if (!effectiveCurrency) return n;
    if (['JPY', 'KRW'].includes(effectiveCurrency)) return n;
    if (Math.abs(n - Math.round(n)) > 1e-9) return n;
    if (n >= 1000) {
      normalizedPriceHints.push('integer_price_normalized_from_minor_units');
      return n / 100;
    }
    return n;
  };

  return {
    id: product?.id ?? null,
    handle: product?.handle ?? null,
    title: product?.title ?? null,
    description: product?.description ?? product?.body_html ?? null,
    vendor: product?.vendor ?? null,
    product_type: product?.product_type ?? product?.type ?? null,
    tags: Array.isArray(product?.tags) ? product.tags : [],
    status: product?.status ?? null,
    published_at: product?.published_at ?? null,
    url: sourceUrl,
    currency_code: effectiveCurrency,
    currency_source: payloadCurrency ? 'product_payload' : (currencyCode ? 'cart' : null),
    currency_warning: payloadCurrencyRaw && payloadCurrencyRaw.length !== 3 ? `invalid_payload_currency:${payloadCurrencyRaw}` : null,
    first_image: images[0] ?? null,
    image_urls: images
      .map((item) => {
        if (typeof item === 'string') return item.trim();
        if (item && typeof item === 'object' && typeof item.src === 'string') return item.src.trim();
        return '';
      })
      .filter(Boolean),
    images_count: images.length,
    variants_count: variants.length,
    variants: variants.map((variant) => ({
      id: variant?.id ?? null,
      title: variant?.title ?? null,
      sku: variant?.sku ?? null,
      available: Boolean(variant?.available),
      price: normalizeJsPriceIfNeeded(variant?.price),
      compare_at_price: normalizeJsPriceIfNeeded(variant?.compare_at_price),
      currency_code: effectiveCurrency,
      option1: variant?.option1 ?? null,
      option2: variant?.option2 ?? null,
      option3: variant?.option3 ?? null,
    })),
    normalization_hints: normalizedPriceHints.length ? [...new Set(normalizedPriceHints)] : [],
  };
}

async function runPromisePool(items, worker, concurrency) {
  const cap = Math.max(1, Number(concurrency || 1));
  let idx = 0;
  const workers = Array.from({ length: Math.min(cap, items.length || 0) }, async () => {
    while (idx < items.length) {
      const current = idx;
      idx += 1;
      await worker(items[current], current);
    }
  });
  await Promise.all(workers);
}

async function fetchTextWithRetries(bridge, url, maxRetries = 7) {
  let lastErr = 'unknown';
  for (let attempt = 1; attempt <= maxRetries; attempt += 1) {
    try {
      const res = await bridge.send('fetch_text', { url, max_retries: 2 }, 120000);
      if (res?.ok && typeof res.body === 'string') {
        return { ok: true, body: res.body, status: res.status };
      }
      lastErr = res?.error || `status_${res?.status ?? 'unknown'}`;
    } catch (err) {
      lastErr = String(err?.message || err);
    }
    await sleep(Math.min(2 ** attempt * 600, 15000));
  }
  return { ok: false, error: lastErr };
}

function logStep(message) {
  console.log(`[scenario:shopify] ${message}`);
}

async function setOverlay(bridge, text, tone = 'info') {
  try {
    await bridge.send('status_overlay', { text, tone }, 15000);
  } catch {
    // non-blocking UI helper
  }
}

export async function runShopifySitemapScenario({ bridge, baseUrl, options }) {
  const startedAt = new Date().toISOString();
  const report = {
    scenario_id: 'shopify-sitemap',
    started_at: startedAt,
    target_base_url: baseUrl,
    product_sitemap_total: 0,
    product_sitemap_processed: 0,
    product_sitemap_failed: 0,
    unique_product_urls: 0,
    js_sample_size: 0,
    js_sample_success: 0,
    js_sample_failed: 0,
    js_sample_429: 0,
    errors: [],
    notes: [],
    extraction_mode: 'sitemap_api',
    products_export: {
      enabled: false,
      products_total: 0,
      products_exported: 0,
      products_failed: 0,
      failed_reasons: {},
    },
  };

  const maxSitemaps = Number(options.maxSitemaps || 24);
  const jsSampleSize = Number(options.jsSampleSize || 80);
  const forceLiveFallback = Boolean(options.forceLiveFallback);
  const exportProducts = Boolean(options.exportProducts);
  const exportConcurrency = Number(options.exportConcurrency || 8);

  logStep(`start base=${baseUrl} maxSitemaps=${maxSitemaps} jsSample=${jsSampleSize}`);
  await setOverlay(bridge, 'Запуск сценария и открытие сайта...');
  await bridge.send('navigate', { url: `${baseUrl}/` }, 30000);
  logStep('navigated to homepage');
  await sleep(1800);
  try {
    await bridge.send('highlight_read', { selector: 'body' }, 15000);
  } catch {
    // optional visual hint only
  }

  logStep('fetching sitemap.xml');
  await setOverlay(bridge, 'Читаю sitemap.xml...');
  const sitemapResp = await fetchTextWithRetries(bridge, `${baseUrl}/sitemap.xml`, 8);
  if (!sitemapResp.ok) {
    report.errors.push(`sitemap.xml failed: ${sitemapResp.error}`);
    logStep(`sitemap.xml failed: ${sitemapResp.error}`);
    await setOverlay(bridge, `Ошибка sitemap.xml: ${sitemapResp.error}`, 'error');
    report.finished_at = new Date().toISOString();
    return report;
  }
  logStep(`sitemap.xml ok status=${sitemapResp.status ?? 'unknown'}`);

  const productSitemaps = parseSitemapIndex(sitemapResp.body).slice(0, maxSitemaps);
  report.product_sitemap_total = productSitemaps.length;
  logStep(`product sitemaps discovered=${productSitemaps.length}`);
  await setOverlay(bridge, `Найдено product-sitemap: ${productSitemaps.length}`);

  const productUrls = new Set();
  for (let index = 0; index < productSitemaps.length; index += 1) {
    const sitemapUrl = productSitemaps[index];
    logStep(`sitemap ${index + 1}/${productSitemaps.length} -> ${sitemapUrl}`);
    await setOverlay(bridge, `Обрабатываю sitemap ${index + 1}/${productSitemaps.length}`);
    const item = await fetchTextWithRetries(bridge, sitemapUrl, 8);
    if (!item.ok) {
      report.product_sitemap_failed += 1;
      report.errors.push(`sitemap failed: ${sitemapUrl} :: ${item.error}`);
      logStep(`sitemap failed ${index + 1}/${productSitemaps.length}: ${item.error}`);
      await setOverlay(bridge, `Ошибка sitemap ${index + 1}: ${item.error}`, 'warn');
      continue;
    }
    const before = productUrls.size;
    for (const url of parseProductUrls(item.body)) {
      const normalized = normalizeProductUrl(url, baseUrl);
      if (normalized) {
        productUrls.add(normalized);
      }
    }
    report.product_sitemap_processed += 1;
    const added = productUrls.size - before;
    logStep(`sitemap ok ${index + 1}/${productSitemaps.length}, +${added}, total=${productUrls.size}`);
    await sleep(450 + Math.floor(Math.random() * 800));
  }

  report.unique_product_urls = productUrls.size;
  logStep(`unique product urls=${report.unique_product_urls}`);
  await setOverlay(bridge, `Собрано URL товаров: ${report.unique_product_urls}`);

  const sample = [...productUrls].slice(0, jsSampleSize);
  report.js_sample_size = sample.length;
  logStep(`products.js sample size=${report.js_sample_size}`);
  await setOverlay(bridge, `Проверяю products.js (${report.js_sample_size} шт.)...`);

  for (let i = 0; i < sample.length; i += 1) {
    const productUrl = sample[i];
    if (i % 10 === 0 || i === sample.length - 1) {
      logStep(`products.js progress ${i + 1}/${sample.length}`);
      await setOverlay(bridge, `Проверка products.js: ${i + 1}/${sample.length}`);
    }
    const handle = handleFromProductUrl(productUrl);
    if (!handle) {
      report.js_sample_failed += 1;
      continue;
    }
    try {
      const res = await bridge.send('fetch_json', {
        url: `${baseUrl}/products/${handle}.js`,
        max_retries: 2,
      }, 120000);
      if (res?.ok && res?.body && (res.body.id || res.body.handle)) {
        report.js_sample_success += 1;
      } else {
        if (res?.status === 429 || res?.error === 'HTTP_429') {
          report.js_sample_429 += 1;
        }
        report.js_sample_failed += 1;
      }
    } catch (err) {
      if (String(err?.message || err).includes('429')) {
        report.js_sample_429 += 1;
      }
      report.js_sample_failed += 1;
    }
  }
  logStep(
    `products.js done success=${report.js_sample_success} failed=${report.js_sample_failed} http429=${report.js_sample_429}`,
  );
  try {
    await bridge.send('highlight_read', { selector: 'body' }, 15000);
  } catch {
    // optional visual hint only
  }

  report.finished_at = new Date().toISOString();
  logStep('finished');
  await setOverlay(
    bridge,
    `Готово: URL=${report.unique_product_urls}, js ok=${report.js_sample_success}, js fail=${report.js_sample_failed}`,
    'success',
  );

  const needFallback =
    forceLiveFallback ||
    report.unique_product_urls === 0 ||
    (report.js_sample_size > 0 && report.js_sample_success === 0) ||
    (report.product_sitemap_processed === 0 && report.product_sitemap_total > 0);

  if (needFallback) {
    logStep('primary mode degraded, switching to live DOM fallback');
    await setOverlay(bridge, 'Переключаюсь на fallback: живой обход...', 'warn');
    const fallback = await runLiveDomFallback({ bridge, baseUrl, options });
    report.extraction_mode = 'sitemap_api+live_dom_fallback';
    report.fallback = fallback;
    if (fallback.unique_product_urls > report.unique_product_urls) {
      report.notes.push('fallback improved product url coverage');
      report.unique_product_urls = fallback.unique_product_urls;
    }
  }

  if (exportProducts) {
    let currencyCode = null;
    try {
      const cart = await bridge.send('fetch_json', { url: `${baseUrl}/cart.js`, max_retries: 2 }, 45000);
      if (cart?.ok && typeof cart?.body?.currency === 'string' && cart.body.currency.trim()) {
        currencyCode = cart.body.currency.trim().toUpperCase();
      }
    } catch {
      // currency is optional
    }

    const allProductUrls = [...productUrls];
    const exportedProducts = [];
    const exportFailures = [];
    report.products_export.enabled = true;
    report.products_export.products_total = allProductUrls.length;
    report.products_export.products_exported = 0;
    report.products_export.products_failed = 0;

    logStep(`export products enabled, total=${allProductUrls.length}, concurrency=${exportConcurrency}`);
    await setOverlay(bridge, `Экспорт товаров: 0/${allProductUrls.length}`);

    let completed = 0;
    try {
      await runPromisePool(
        allProductUrls,
        async (productUrl, index) => {
          const handle = handleFromProductUrl(productUrl);
          if (!handle) {
            exportFailures.push({ url: productUrl, reason: 'empty_handle' });
            completed += 1;
            return;
          }
          try {
            const res = await bridge.send('fetch_json', {
              url: `${baseUrl}/products/${handle}.js`,
              max_retries: 3,
            }, 120000);
            if (res?.ok && res?.body && (res.body.id || res.body.handle)) {
              exportedProducts.push(mapProductForExport(res.body, productUrl, currencyCode));
            } else {
              const reason = res?.error || `status_${res?.status ?? 'unknown'}`;
              exportFailures.push({ url: productUrl, handle, reason, status: res?.status ?? null });
            }
          } catch (err) {
            exportFailures.push({ url: productUrl, handle, reason: String(err?.message || err) });
          }
          completed += 1;
          if (completed % 100 === 0 || completed === allProductUrls.length || index === 0) {
            logStep(`export progress ${completed}/${allProductUrls.length}`);
            await setOverlay(bridge, `Экспорт товаров: ${completed}/${allProductUrls.length}`);
          }
        },
        exportConcurrency,
      );
    } catch (err) {
      const reason = String(err?.message || err);
      report.errors.push(`export aborted early: ${reason}`);
      report.notes.push('partial export preserved');
      logStep(`export aborted early: ${reason}`);
      await setOverlay(bridge, `Экспорт прерван, сохраняю частичный результат (${completed})`, 'warn');
    }

    report.products_export.products_exported = exportedProducts.length;
    report.products_export.products_failed = exportFailures.length;
    for (const item of exportFailures) {
      const key = String(item.reason || 'unknown');
      report.products_export.failed_reasons[key] = (report.products_export.failed_reasons[key] || 0) + 1;
    }

    report.artifacts = {
      products: exportedProducts,
      failed_products: exportFailures,
    };
    logStep(
      `export done exported=${report.products_export.products_exported} failed=${report.products_export.products_failed}`,
    );
    await setOverlay(
      bridge,
      `Экспорт завершён: ok=${report.products_export.products_exported}, fail=${report.products_export.products_failed}`,
      'success',
    );
  }

  return report;
}
