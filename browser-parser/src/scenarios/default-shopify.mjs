import { runShopifySitemapScenario } from './shopify-sitemap-scenario.mjs';

export const defaultShopifyScenario = {
  id: 'default-shopify-sitemap',
  matches: () => true,
  run: async ({ bridge, baseUrl, env }) => {
    return runShopifySitemapScenario({
      bridge,
      baseUrl,
      options: {
        maxSitemaps: Number(env.BROWSER_PARSER_MAX_PRODUCT_SITEMAPS || 24),
        jsSampleSize: Number(env.BROWSER_PARSER_JS_SAMPLE_SIZE || 80),
        forceLiveFallback: String(env.BROWSER_PARSER_FORCE_LIVE_FALLBACK || 'false').toLowerCase() === 'true',
        exportProducts: String(env.BROWSER_PARSER_EXPORT_PRODUCTS || 'true').toLowerCase() === 'true',
        exportConcurrency: Number(env.BROWSER_PARSER_EXPORT_CONCURRENCY || 8),
      },
    });
  },
};
