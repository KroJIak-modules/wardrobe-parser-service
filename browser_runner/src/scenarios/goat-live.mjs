function logGoat(message) {
  console.log(`[scenario:goat] ${message}`);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function unique(items) {
  return [...new Set(items)];
}

function extractNextData(html) {
  const m = html.match(/<script[^>]*id=["']__NEXT_DATA__["'][^>]*>([\s\S]*?)<\/script>/i);
  if (!m || !m[1]) return null;
  try {
    return JSON.parse(m[1]);
  } catch {
    return null;
  }
}

function extractPriceFromJsonLd(html) {
  try {
    const blocks = [...html.matchAll(/<script[^>]*type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi)];
    for (const m of blocks) {
      const raw = String(m?.[1] || '').trim();
      if (!raw) continue;
      let data = null;
      try {
        data = JSON.parse(raw);
      } catch {
        continue;
      }
      const list = Array.isArray(data) ? data : [data];
      for (const node of list) {
        const offers = node?.offers;
        const offersList = Array.isArray(offers) ? offers : (offers ? [offers] : []);
        for (const offer of offersList) {
          const candidate = offer?.price ?? offer?.lowPrice ?? offer?.highPrice;
          const n = Number(candidate);
          if (Number.isFinite(n) && n > 0) return n;
        }
      }
    }
  } catch {
    return null;
  }
  return null;
}

function slugFromProductUrl(productUrl) {
  try {
    const u = new URL(productUrl);
    const parts = String(u.pathname || '').split('/').filter(Boolean);
    return parts[parts.length - 1] || '';
  } catch {
    return '';
  }
}

function findPositivePriceDeep(node, depth = 0) {
  if (depth > 8 || node === null || node === undefined) return null;
  if (typeof node === 'number' && Number.isFinite(node) && node > 0) return node;
  if (typeof node === 'string') {
    const n = Number(node);
    if (Number.isFinite(n) && n > 0) return n;
    return null;
  }
  if (Array.isArray(node)) {
    for (const item of node) {
      const found = findPositivePriceDeep(item, depth + 1);
      if (found !== null) return found;
    }
    return null;
  }
  if (typeof node === 'object') {
    // Prioritize likely price keys.
    for (const key of ['price', 'lowestPrice', 'lowestPriceCents', 'retailPrice', 'amount']) {
      if (Object.prototype.hasOwnProperty.call(node, key)) {
        const raw = node[key];
        const n = Number(raw);
        if (Number.isFinite(n) && n > 0) {
          if (String(key).toLowerCase().includes('cents')) return n / 100;
          return n;
        }
      }
    }
    for (const value of Object.values(node)) {
      const found = findPositivePriceDeep(value, depth + 1);
      if (found !== null) return found;
    }
  }
  return null;
}

async function fetchGoatApiPrice(bridge, productUrl) {
  const slug = slugFromProductUrl(productUrl);
  if (!slug) return null;
  const endpoints = [
    `https://www.goat.com/web-api/v1/product_templates/${slug}/show_v2`,
    `https://www.goat.com/web-api/v1/product_templates/${slug}`,
    `https://www.goat.com/api/v1/product_templates/${slug}/show_v2`,
    `https://www.goat.com/api/v1/product_templates/${slug}`,
  ];
  for (const url of endpoints) {
    try {
      const res = await bridge.send('fetch_json', { url, max_retries: 1 }, 90000);
      if (!res?.ok || !res?.json) continue;
      const found = findPositivePriceDeep(res.json);
      if (found !== null && Number(found) > 0) return Number(found);
    } catch {
      // ignore and continue
    }
  }
  return null;
}

async function extractPageRuntimePrice(bridge, productUrl) {
  try {
    await bridge.send('navigate', { url: productUrl }, 45000);
    await sleep(2500);
    const probeScript = `(() => {
      const out = {};
      const toNum = (v) => {
        const n = Number(v);
        return Number.isFinite(n) ? n : null;
      };
      const pick = (...vals) => {
        for (const v of vals) {
          const n = toNum(v);
          if (n !== null && n > 0) return n;
        }
        return null;
      };
      // 1) JSON-LD
      const blocks = Array.from(document.querySelectorAll('script[type=\"application/ld+json\"]'));
      for (const b of blocks) {
        try {
          const data = JSON.parse(b.textContent || '{}');
          const list = Array.isArray(data) ? data : [data];
          for (const node of list) {
            const offers = Array.isArray(node?.offers) ? node.offers : (node?.offers ? [node.offers] : []);
            for (const off of offers) {
              const p = pick(off?.price, off?.lowPrice, off?.highPrice);
              if (p) return { price: p, source: 'jsonld' };
            }
          }
        } catch {}
      }
      // 2) __NEXT_DATA__
      const node = document.getElementById('__NEXT_DATA__');
      if (node && node.textContent) {
        try {
          const next = JSON.parse(node.textContent);
          const stack = [next?.props?.pageProps || {}];
          while (stack.length) {
            const cur = stack.pop();
            if (!cur) continue;
            if (Array.isArray(cur)) {
              for (const x of cur) if (x && typeof x === 'object') stack.push(x);
              continue;
            }
            if (typeof cur === 'object') {
              const p = pick(cur.price, cur.lowestPrice, cur.retailPrice, (toNum(cur.lowestPriceCents) || 0) / 100);
              if (p) return { price: p, source: 'next_data' };
              const sizes = Array.isArray(cur.sizes) ? cur.sizes : [];
              for (const s of sizes) {
                const sp = pick(s?.price, s?.lowestPrice, (toNum(s?.lowestPriceCents) || 0) / 100);
                if (sp) return { price: sp, source: 'next_data_sizes' };
              }
              for (const v of Object.values(cur)) if (v && typeof v === 'object') stack.push(v);
            }
          }
        } catch {}
      }
      return { price: null, source: 'none' };
    })()`;
    const res = await bridge.send('execute_js', { script: probeScript }, 60000);
    if (!res?.ok || !res?.value) return null;
    const n = Number(res.value?.price);
    if (Number.isFinite(n) && n > 0) return n;
    return null;
  } catch {
    return null;
  }
}

function firstNonEmpty(...vals) {
  for (const v of vals) {
    if (v === null || v === undefined) continue;
    if (typeof v === 'string' && !v.trim()) continue;
    return v;
  }
  return null;
}

function toNumberOrNull(v) {
  if (v === null || v === undefined) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function candidatePriceScore(candidate) {
  const direct = [candidate?.price, candidate?.retailPrice, candidate?.lowestPrice, candidate?.lowestPriceCents];
  for (const raw of direct) {
    const n = toNumberOrNull(raw);
    if (n !== null && n > 0) return n;
  }
  const sizes = Array.isArray(candidate?.sizes) ? candidate.sizes : [];
  let best = 0;
  for (const s of sizes) {
    const vals = [s?.price, s?.lowestPrice];
    for (const raw of vals) {
      const n = toNumberOrNull(raw);
      if (n !== null && n > best) best = n;
    }
    const cents = toNumberOrNull(s?.lowestPriceCents);
    if (cents !== null && cents > best) best = cents / 100;
  }
  return best;
}

function collectImages(payload) {
  const out = [];
  const push = (value) => {
    if (typeof value === 'string' && value.trim()) out.push(value.trim());
  };
  push(payload?.imageUrl);
  push(payload?.pictureUrl);
  push(payload?.mainPictureUrl);
  for (const key of ['images', 'imageUrls', 'gallery', 'galleryPictures']) {
    const list = payload?.[key];
    if (!Array.isArray(list)) continue;
    for (const item of list) {
      if (typeof item === 'string') push(item);
      else if (item && typeof item === 'object') push(item.url || item.imageUrl || item.src);
    }
  }
  return unique(out);
}

function parseProductFromNextData(nextData, productUrl, html = '') {
  const props = typeof nextData?.props === 'object' ? nextData.props : {};
  const pageProps = typeof props?.pageProps === 'object' ? props.pageProps : {};
  const stack = [pageProps];
  const allCandidates = [];
  const urlSlug = (() => {
    try {
      const u = new URL(productUrl);
      const parts = String(u.pathname || '').split('/').filter(Boolean);
      return parts[parts.length - 1] || '';
    } catch {
      return '';
    }
  })();

  while (stack.length) {
    const current = stack.pop();
    if (current && typeof current === 'object' && !Array.isArray(current)) {
      if ((current.name || current.slug) && (current.retailPrice !== undefined || current.lowestPrice !== undefined || current.price !== undefined || current.lowestPriceCents !== undefined)) {
        allCandidates.push(current);
      }
      for (const v of Object.values(current)) {
        if (v && (typeof v === 'object')) stack.push(v);
      }
    } else if (Array.isArray(current)) {
      for (const v of current) {
        if (v && typeof v === 'object') stack.push(v);
      }
    }
  }
  if (!allCandidates.length) return null;
  const scored = allCandidates
    .map((c) => {
      const slug = String(firstNonEmpty(c.slug, c.id, '') || '');
      const slugMatch = urlSlug && slug ? (slug === urlSlug ? 1 : (urlSlug.includes(slug) || slug.includes(urlSlug) ? 0.5 : 0)) : 0;
      const priceScore = candidatePriceScore(c);
      const sizesCount = Array.isArray(c?.sizes) ? c.sizes.length : 0;
      return {
        c,
        total: (slugMatch * 1000000) + (priceScore * 1000) + sizesCount,
      };
    })
    .sort((a, b) => b.total - a.total);
  const candidate = scored[0].c;

  const currency = String(firstNonEmpty(candidate.currency, candidate.currencyCode, 'USD') || 'USD').toUpperCase();
  let price = firstNonEmpty(candidate.price, candidate.retailPrice, candidate.lowestPrice);
  if (price === null || price === undefined) {
    const cents = candidate.lowestPriceCents;
    if (cents !== null && cents !== undefined && Number.isFinite(Number(cents))) {
      price = Number(cents) / 100;
    }
  }
  const parsedPrice = toNumberOrNull(price);
  if (parsedPrice !== null) price = parsedPrice;

  const sizes = Array.isArray(candidate.sizes) ? candidate.sizes : [];
  const variants = [];
  for (let i = 0; i < sizes.length; i += 1) {
    const s = sizes[i] || {};
    const sizeLabel = firstNonEmpty(s.size, s.name, s.label, `size-${i + 1}`);
    let variantPrice = firstNonEmpty(s.price, s.lowestPrice);
    if ((variantPrice === null || variantPrice === undefined) && s.lowestPriceCents !== undefined && s.lowestPriceCents !== null) {
      variantPrice = Number(s.lowestPriceCents) / 100;
    }
    const parsedVariantPrice = toNumberOrNull(variantPrice);
    variants.push({
      id: firstNonEmpty(s.id, `size-${i + 1}`),
      title: String(sizeLabel || `size-${i + 1}`),
      option1: String(sizeLabel || ''),
      option2: null,
      option3: null,
      sku: firstNonEmpty(s.sku, null),
      available: Boolean(firstNonEmpty(s.available, s.inStock, parsedVariantPrice !== null && parsedVariantPrice > 0)),
      price: parsedVariantPrice,
      compare_at_price: null,
      inventory_quantity: null,
    });
  }
  const nonZeroVariant = variants.find((v) => Number(v.price || 0) > 0);
  if ((price === null || Number(price) <= 0) && nonZeroVariant) {
    price = Number(nonZeroVariant.price);
  }

  if (!variants.length) {
    variants.push({
      id: String(firstNonEmpty(candidate.id, candidate.slug, 'default')),
      title: 'Default',
      option1: null,
      option2: null,
      option3: null,
      sku: null,
      available: price !== null && price !== undefined,
      price,
      compare_at_price: null,
      inventory_quantity: null,
    });
  }
  if (price === null || Number(price) <= 0) {
    const ldPrice = extractPriceFromJsonLd(html);
    if (ldPrice !== null && ldPrice > 0) {
      price = ldPrice;
      for (const v of variants) {
        if (Number(v.price || 0) <= 0) v.price = ldPrice;
      }
    }
  }

  return {
    url: String(productUrl),
    handle: String(firstNonEmpty(candidate.slug, candidate.id, '') || ''),
    title: String(firstNonEmpty(candidate.name, candidate.title, '') || ''),
    description: firstNonEmpty(candidate.description, candidate.story, candidate.details) || null,
    vendor: firstNonEmpty(candidate.brandName, candidate.brand, candidate.designer) || null,
    product_type: String(firstNonEmpty(candidate.category, candidate.silhouette, 'Sneakers') || 'Sneakers'),
    currency_code: currency,
    image_urls: collectImages(candidate),
    variants,
    __debug: {
      candidate_slug: String(firstNonEmpty(candidate.slug, '') || ''),
      candidate_id: String(firstNonEmpty(candidate.id, '') || ''),
      candidate_price: firstNonEmpty(candidate.price, null),
      candidate_lowestPrice: firstNonEmpty(candidate.lowestPrice, null),
      candidate_retailPrice: firstNonEmpty(candidate.retailPrice, null),
      candidate_lowestPriceCents: firstNonEmpty(candidate.lowestPriceCents, null),
      sizes_count: Array.isArray(candidate.sizes) ? candidate.sizes.length : 0,
    },
  };
}

export const goatLiveScenario = {
  id: 'goat-live',
  matches: (url) => {
    try {
      const host = new URL(url).hostname.toLowerCase();
      return host === 'www.goat.com' || host === 'goat.com';
    } catch {
      return false;
    }
  },
  run: async ({ bridge, baseUrl, options = {}, extensionConnected }) => {
    if (!bridge || !extensionConnected || !bridge.isConnected?.()) {
      throw new Error('goat_live_requires_browser_extension');
    }

    const startedAt = new Date().toISOString();
    const maxProducts = Number(options.exportMaxProducts || 60);
    const searchQuery = String(options.searchQuery || 'jordan');
    const searchUrl = `${baseUrl}/search?query=${encodeURIComponent(searchQuery)}`;

    // Do not call content-script actions on about:blank before first navigation.
    await bridge.send('navigate', { url: searchUrl }, 45000);
    await sleep(3200);
    await bridge.send('status_overlay', { text: 'GOAT: открываем поиск...', tone: 'info' }, 15000);

    const linksPayload = await bridge.send('collect_links', { selector: 'a[href*="/sneakers/"]', limit: Math.max(200, maxProducts * 4) }, 45000);
    const rawLinks = Array.isArray(linksPayload?.links) ? linksPayload.links : [];
    const productUrls = unique(
      rawLinks
        .map((u) => {
          try {
            const p = new URL(u, baseUrl);
            if (!p.pathname.includes('/sneakers/')) return '';
            p.search = '';
            p.hash = '';
            return p.toString();
          } catch {
            return '';
          }
        })
        .filter(Boolean),
    ).slice(0, maxProducts);

    logGoat(`discovered=${productUrls.length}`);

    const products = [];
    const failedProducts = [];
    let firstDebug = null;

    for (let i = 0; i < productUrls.length; i += 1) {
      const url = productUrls[i];
      if (i % 5 === 0 || i === productUrls.length - 1) {
        await bridge.send('status_overlay', { text: `GOAT: товар ${i + 1}/${productUrls.length}`, tone: 'info' }, 15000);
      }
      const fetched = await bridge.send('fetch_text', { url, max_retries: 2 }, 90000);
      if (!fetched?.ok || typeof fetched?.body !== 'string') {
        const reason = String(fetched?.error || `HTTP_${fetched?.status || 'fetch_failed'}`);
        failedProducts.push({ url, reason });
        if (String(reason).includes('HTTP_429') || String(reason).includes('429')) {
          throw new Error(`HTTP_429 on ${url}`);
        }
        continue;
      }
      const nextData = extractNextData(fetched.body);
      if (!nextData) {
        failedProducts.push({ url, reason: 'next_data_not_found' });
        continue;
      }
      const parsed = parseProductFromNextData(nextData, url, fetched.body);
      if (!parsed || !parsed.url || !parsed.handle || !parsed.title) {
        failedProducts.push({ url, reason: 'product_payload_not_found' });
        continue;
      }
      if (!(Number(parsed?.variants?.[0]?.price || 0) > 0) || !(Number(parsed?.price || 0) > 0)) {
        const apiPrice = await fetchGoatApiPrice(bridge, url);
        let patchedPrice = apiPrice;
        if (!(patchedPrice !== null && patchedPrice > 0)) {
          patchedPrice = await extractPageRuntimePrice(bridge, url);
        }
        if (patchedPrice !== null && patchedPrice > 0) {
          parsed.price = patchedPrice;
          if (Array.isArray(parsed.variants) && parsed.variants.length) {
            for (const v of parsed.variants) {
              if (!(Number(v?.price || 0) > 0)) v.price = patchedPrice;
            }
          }
        }
      }
      if (!firstDebug) {
        firstDebug = {
          url,
          parsed_price: parsed?.price ?? null,
          parsed_variant_prices: Array.isArray(parsed?.variants) ? parsed.variants.map((v) => v?.price ?? null).slice(0, 10) : [],
          parsed_variant_titles: Array.isArray(parsed?.variants) ? parsed.variants.map((v) => v?.title ?? null).slice(0, 10) : [],
          debug_candidate: parsed?.__debug || null,
        };
      }
      products.push(parsed);
    }

    const report = {
      scenario_id: 'goat-live',
      extraction_mode: 'goat_next_data',
      started_at: startedAt,
      finished_at: new Date().toISOString(),
      unique_product_urls: productUrls.length,
      warnings: [],
      errors: [],
      notes: [`search_query=${searchQuery}`],
      products_export: {
        products_total: products.length + failedProducts.length,
        products_failed: failedProducts.length,
      },
      artifacts: {
        products,
        failed_products: failedProducts,
        debug_first: firstDebug,
      },
    };
    return report;
  },
};
