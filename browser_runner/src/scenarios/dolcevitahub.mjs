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
  run: async ({ bridge, baseUrl, options = {} }) => {
    return runShopifySitemapScenario({
      bridge,
      baseUrl,
      options: {
        maxSitemaps: Number(options.maxSitemaps || 24),
        jsSampleSize: Number(options.jsSampleSize || 120),
        forceLiveFallback: Boolean(options.forceLiveFallback),
        exportProducts: options.exportProducts !== false,
        exportConcurrency: Number(options.exportConcurrency || 8),
        exportMode: String(options.exportMode || 'json'),
        exportMaxProducts: Number(options.exportMaxProducts || 0),
      },
    });
  },
};
