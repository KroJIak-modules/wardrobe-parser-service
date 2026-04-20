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
  return {
    product_url: item?.url || '',
    handle: item?.handle || '',
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

function buildOutputPayload({ baseUrl, report }) {
  const artifacts = report?.artifacts || {};
  const products = Array.isArray(artifacts.products) ? artifacts.products : [];
  const failures = Array.isArray(artifacts.failed_products) ? artifacts.failed_products : [];
  const previews = products
    .map((item) => toPreview(item))
    .filter((item) => item.product_url && item.handle);

  const warnings = []
    .concat(Array.isArray(report?.warnings) ? report.warnings : [])
    .concat(Array.isArray(report?.notes) ? report.notes : []);
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
  const baseUrl = (args['base-url'] || process.env.BROWSER_PARSER_TARGET_URL || '').trim().replace(/\/$/, '');
  if (!baseUrl) {
    throw new Error('Missing --base-url');
  }

  const wsPort = parseNumber(args['ws-port'] || process.env.BROWSER_PARSER_WS_PORT, 8777);
  const browserBinary = (args['browser-binary'] || process.env.BROWSER_PARSER_BROWSER_BIN || 'chromium').trim();
  const showUi = parseBoolean(args['show-ui'] || process.env.BROWSER_PARSER_SHOW_UI, false);
  const scenarioId = (args['scenario-id'] || process.env.BROWSER_PARSER_SCENARIO_ID || '').trim();

  const bridge = new ExtensionBridge(wsPort);
  const browserEnv = await startBrowserEnvironment({ browserBinary, showUi });

  let exitCode = 0;
  try {
    await bridge.waitForConnection(parseNumber(args['wait-extension-timeout-ms'], 120000));
    const ping = await bridge.send('ping', {}, 15000);
    if (!ping?.pong) {
      throw new Error('Extension ping failed');
    }

    const env = {
      ...process.env,
      BROWSER_PARSER_MAX_PRODUCT_SITEMAPS: String(
        parseNumber(args['max-sitemaps'] || process.env.BROWSER_PARSER_MAX_PRODUCT_SITEMAPS, 24),
      ),
      BROWSER_PARSER_JS_SAMPLE_SIZE: String(
        parseNumber(args['js-sample-size'] || process.env.BROWSER_PARSER_JS_SAMPLE_SIZE, 80),
      ),
      BROWSER_PARSER_FORCE_LIVE_FALLBACK: String(
        parseBoolean(args['force-live-fallback'] || process.env.BROWSER_PARSER_FORCE_LIVE_FALLBACK, false),
      ),
      BROWSER_PARSER_EXPORT_PRODUCTS: String(
        parseBoolean(args['export-products'] || process.env.BROWSER_PARSER_EXPORT_PRODUCTS, true),
      ),
      BROWSER_PARSER_EXPORT_CONCURRENCY: String(
        parseNumber(args['export-concurrency'] || process.env.BROWSER_PARSER_EXPORT_CONCURRENCY, 8),
      ),
    };

    const scenario = resolveScenario(baseUrl, scenarioId);
    const report = await scenario.run({
      bridge,
      baseUrl,
      env,
    });
    const output = buildOutputPayload({ baseUrl, report });
    // Keep last line pure JSON for parser client.
    process.stdout.write(`${JSON.stringify(output)}\n`);
  } catch (err) {
    exitCode = 1;
    const message = String(err?.stack || err);
    process.stderr.write(`${message}\n`);
  } finally {
    await bridge.close();
    await browserEnv.stop();
  }

  process.exit(exitCode);
}

main();
