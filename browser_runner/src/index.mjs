import { ExtensionBridge } from './core/extension-bridge.mjs';
import { startBrowserEnvironment } from './core/browser-launcher.mjs';
import { resolveScenario } from './scenarios/registry.mjs';

function parseBoolean(value, fallback = false) {
  if (value === undefined || value === null || value === '') return fallback;
  return String(value).toLowerCase() === 'true';
}

function parseNumber(value, fallback) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith('--')) continue;
    const key = token.slice(2);
    const next = argv[i + 1];
    if (next && !next.startsWith('--')) {
      args[key] = next;
      i += 1;
    } else {
      args[key] = 'true';
    }
  }
  return args;
}

function minVariantPrice(variants) {
  if (!Array.isArray(variants) || variants.length === 0) return null;
  let min = null;
  for (const variant of variants) {
    const raw = variant?.price;
    if (raw === null || raw === undefined || raw === '') continue;
    const n = Number(raw);
    if (!Number.isFinite(n)) continue;
    if (min === null || n < min) min = n;
  }
  return min;
}

function countHttp429FromFailures(failures) {
  if (!Array.isArray(failures)) return 0;
  let count = 0;
  for (const item of failures) {
    const reason = String(item?.reason || '').toLowerCase();
    if (reason.includes('429') || reason.includes('http_429')) {
      count += 1;
    }
  }
  return count;
}

function toPreview(item) {
  const variants = Array.isArray(item?.variants) ? item.variants : [];
  const availableByStatus = String(item?.status || '').toLowerCase() !== 'out_of_stock';
  const variantPayload = variants.map((variant) => ({
    title: variant?.title ?? null,
    option1: variant?.option1 ?? null,
    option2: variant?.option2 ?? null,
    option3: variant?.option3 ?? null,
    available: Boolean(variant?.available),
    price: variant?.price ?? null,
    compare_at_price: variant?.compare_at_price ?? null,
    inventory_quantity: null,
    sku: variant?.sku ?? null,
  }));
  const imageUrls = Array.isArray(item?.image_urls)
    ? item.image_urls.filter((value) => typeof value === 'string' && value.trim())
    : [];
  if (!imageUrls.length && typeof item?.first_image === 'string' && item.first_image.trim()) {
    imageUrls.push(item.first_image.trim());
  }
  const minPrice = minVariantPrice(variants);
  const resolvedUrl = item?.url || '';
  const resolvedHandle = item?.handle || handleFromProductUrl(resolvedUrl);
  return {
    product_url: resolvedUrl,
    handle: resolvedHandle,
    title: item?.title || null,
    description: item?.description || null,
    vendor: item?.vendor || null,
    product_type: item?.product_type || null,
    price: minPrice !== null ? String(minPrice) : null,
    currency: item?.currency_code || null,
    image_urls: imageUrls,
    available: variants.length > 0 ? variants.some((variant) => Boolean(variant?.available)) : availableByStatus,
    variants: variantPayload,
    payload_source: 'browser_parser',
  };
}

function handleFromProductUrl(url) {
  const marker = '/products/';
  const idx = String(url || '').indexOf(marker);
  if (idx < 0) return '';
  return String(url).slice(idx + marker.length).split('?')[0].replace(/\/$/, '');
}

function buildOutputPayload({ baseUrl, report }) {
  const artifacts = report?.artifacts || {};
  const products = Array.isArray(artifacts.products) ? artifacts.products : [];
  const failures = Array.isArray(artifacts.failed_products) ? artifacts.failed_products : [];
  const previews = products
    .map((item) => toPreview(item))
    .filter((item) => item.product_url);

  const warnings = []
    .concat(Array.isArray(report?.warnings) ? report.warnings : [])
    .concat(Array.isArray(report?.notes) ? report.notes : []);
  if (artifacts?.debug_first) {
    warnings.push(`debug_first=${JSON.stringify(artifacts.debug_first)}`);
  }
  const errorDetails = []
    .concat(Array.isArray(report?.errors) ? report.errors : [])
    .concat(
      failures.slice(0, 300).map((item) => {
        const url = item?.url || 'unknown-url';
        const reason = item?.reason || 'unknown';
        return `${url} -> ${reason}`;
      }),
    );

  const productsTotal = Number(report?.products_export?.products_total || report?.unique_product_urls || previews.length);
  const productsFailed = Number(report?.products_export?.products_failed || failures.length);
  const productsSucceeded = previews.length;

  return {
    base_url: baseUrl,
    discovery_mode: `browser_parser:${report?.extraction_mode || 'unknown'}`,
    product_urls_found: Number(report?.unique_product_urls || productsTotal || previews.length),
    products_fetch_attempted: productsTotal,
    products_fetch_succeeded: productsSucceeded,
    products_fetch_failed: productsFailed,
    http_429_count: countHttp429FromFailures(failures),
    http_5xx_count: 0,
    warnings,
    error_details: errorDetails,
    previews,
  };
}

async function main() {
  const args = parseArgs(process.argv);
  const baseUrl = (args['base-url'] || '').trim().replace(/\/$/, '');
  if (!baseUrl) {
    throw new Error('Missing --base-url');
  }

  const wsPort = parseNumber(args['ws-port'], 8777);
  const browserBinary = (args['browser-binary'] || 'chromium').trim();
  const showUi = parseBoolean(args['show-ui'], false);
  const networkOnly = parseBoolean(args['network-only'], false);
  const scenarioId = (args['scenario-id'] || '').trim();

  const bridge = networkOnly ? null : new ExtensionBridge(wsPort);
  console.log(
    `[runner] phase=start base_url=${baseUrl} ws_port=${wsPort} scenario_id=${scenarioId || 'auto'} network_only=${networkOnly}`,
  );
  const browserEnv = networkOnly ? null : await startBrowserEnvironment({ browserBinary, showUi });
  if (browserEnv) console.log('[runner] phase=browser_started');

  let exitCode = 0;
  try {
    let extensionConnected = false;
    if (bridge) {
      const waitMs = parseNumber(args['wait-extension-timeout-ms'], 120000);
      console.log(`[runner] phase=waiting_extension timeout_ms=${waitMs}`);
      try {
        await bridge.waitForConnection(waitMs);
        console.log('[runner] phase=extension_connected');
        const ping = await bridge.send('ping', {}, 15000);
        if (!ping?.pong) throw new Error('Extension ping failed');
        console.log('[runner] phase=extension_ping_ok');
        extensionConnected = true;
      } catch (err) {
        console.log(`[runner] phase=extension_unavailable mode=network_only reason=${String(err?.message || err)}`);
      }
    } else {
      console.log('[runner] phase=network_only');
    }

    const options = {
      maxSitemaps: args['max-sitemaps'] !== undefined ? parseNumber(args['max-sitemaps'], 0) : 0,
      jsSampleSize: parseNumber(args['js-sample-size'], 80),
      forceLiveFallback: parseBoolean(args['force-live-fallback'], false),
      exportProducts: parseBoolean(args['export-products'], true),
      exportConcurrency: parseNumber(args['export-concurrency'], 8),
      exportMode: String(args['export-mode'] || 'json').trim().toLowerCase(),
      exportMaxProducts: parseNumber(args['export-max-products'], 0),
      maxCollectionPages: parseNumber(args['max-collection-pages'], 0),
      skipDiscoveryForLimitedJsonExport: parseBoolean(args['skip-discovery-for-limited-json-export'], false),
      currencyPriority: String(args['currency-priority'] || '')
        .split(',')
        .map((x) => String(x || '').trim().toUpperCase())
        .filter(Boolean),
      countryCode: String(args['country-code'] || '').trim().toUpperCase(),
    };

    const scenario = resolveScenario(baseUrl, scenarioId);
    console.log(`[runner] phase=scenario_start scenario=${scenario.id}`);
    const report = await scenario.run({
      bridge,
      baseUrl,
      options,
      extensionConnected,
    });
    console.log('[runner] phase=scenario_done');
    const output = buildOutputPayload({ baseUrl, report });
    // Keep last line pure JSON for parser client.
    process.stdout.write(`${JSON.stringify(output)}\n`);
  } catch (err) {
    exitCode = 1;
    const message = String(err?.stack || err);
    process.stderr.write(`${message}\n`);
  } finally {
    if (bridge) await bridge.close();
    if (browserEnv) await browserEnv.stop();
  }

  process.exit(exitCode);
}

main();
