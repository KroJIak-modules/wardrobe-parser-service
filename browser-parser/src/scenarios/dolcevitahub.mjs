import { runShopifySitemapScenario } from './shopify-sitemap-scenario.mjs';

export const dolcevitahubScenario = {
  id: 'dolcevitahub-shopify-sitemap',
  matches: (url) => {
    try {
      const host = new URL(url).hostname.toLowerCase();
      return host === 'dolcevitahub.com' || host.endsWith('.dolcevitahub.com');
    } catch {
      return false;
    }
  },
  run: async ({ bridge, baseUrl, env }) => {
    return runShopifySitemapScenario({
      bridge,
      baseUrl,
      options: {
        maxSitemaps: Number(env.BROWSER_PARSER_MAX_PRODUCT_SITEMAPS || 24),
        jsSampleSize: Number(env.BROWSER_PARSER_JS_SAMPLE_SIZE || 120),
        forceLiveFallback: String(env.BROWSER_PARSER_FORCE_LIVE_FALLBACK || 'false').toLowerCase() === 'true',
        exportProducts: String(env.BROWSER_PARSER_EXPORT_PRODUCTS || 'true').toLowerCase() === 'true',
        exportConcurrency: Number(env.BROWSER_PARSER_EXPORT_CONCURRENCY || 8),
      },
    });
  },
};
