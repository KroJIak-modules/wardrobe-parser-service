import { runShopifySitemapScenario } from './shopify-sitemap-scenario.mjs';

export const defaultShopifyScenario = {
  id: 'default-shopify-sitemap',
  matches: () => true,
  run: async ({ bridge, baseUrl, options = {} }) => {
    return runShopifySitemapScenario({
      bridge,
      baseUrl,
      options: {
        maxSitemaps: Number(options.maxSitemaps || 24),
        jsSampleSize: Number(options.jsSampleSize || 80),
        forceLiveFallback: Boolean(options.forceLiveFallback),
        exportProducts: options.exportProducts !== false,
        exportConcurrency: Number(options.exportConcurrency || 8),
        exportMode: String(options.exportMode || 'json'),
        exportMaxProducts: Number(options.exportMaxProducts || 0),
      },
    });
  },
};
