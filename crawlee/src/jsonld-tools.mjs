function asArray(value) {
    if (Array.isArray(value)) return value;
    if (value == null) return [];
    return [value];
}

function normalizeType(value) {
    return asArray(value).map((item) => String(item || '').toLowerCase());
}

function deepVisit(value, visitor) {
    if (Array.isArray(value)) {
        for (const item of value) deepVisit(item, visitor);
        return;
    }
    if (!value || typeof value !== 'object') return;
    visitor(value);
    for (const nested of Object.values(value)) deepVisit(nested, visitor);
}

export function parseJsonLdObjects($) {
    const results = [];
    $('script[type="application/ld+json"]').each((_, script) => {
        const raw = $(script).contents().text() || '';
        const trimmed = raw.trim();
        if (!trimmed) return;
        try {
            results.push(JSON.parse(trimmed));
        } catch {
            // ignore malformed snippets
        }
    });
    return results;
}

export function findProductNode(jsonLdObjects) {
    let found = null;
    for (const root of jsonLdObjects) {
        deepVisit(root, (candidate) => {
            if (found) return;
            const types = normalizeType(candidate['@type']);
            if (types.includes('product')) {
                found = candidate;
            }
        });
        if (found) break;
    }
    return found;
}

function extractOffer(productNode) {
    const offers = asArray(productNode?.offers);
    if (offers.length === 0) return null;
    return offers.find((item) => item && typeof item === 'object') || null;
}

function toStringOrNull(value) {
    const normalized = String(value ?? '').trim();
    return normalized || null;
}

function extractImageUrls(productNode) {
    const images = asArray(productNode?.image);
    const out = [];
    for (const item of images) {
        if (typeof item === 'string') out.push(item.trim());
        else if (item && typeof item === 'object' && typeof item.url === 'string') out.push(item.url.trim());
    }
    return [...new Set(out.filter(Boolean))];
}

function extractBrand(productNode) {
    const brand = productNode?.brand;
    if (typeof brand === 'string') return toStringOrNull(brand);
    if (brand && typeof brand === 'object') return toStringOrNull(brand.name);
    return null;
}

function extractAvailability(productNode) {
    const offer = extractOffer(productNode);
    const raw = String(offer?.availability || '').toLowerCase();
    if (!raw) return true;
    if (raw.includes('outofstock') || raw.includes('soldout')) return false;
    return true;
}

export function buildProductFromJsonLd(productNode) {
    const offer = extractOffer(productNode);
    const price = toStringOrNull(offer?.price);
    const currency = toStringOrNull(offer?.priceCurrency)?.toUpperCase() || null;
    return {
        title: toStringOrNull(productNode?.name),
        description: toStringOrNull(productNode?.description),
        vendor: extractBrand(productNode),
        product_type: toStringOrNull(productNode?.category),
        price,
        currency,
        image_urls: extractImageUrls(productNode),
        available: extractAvailability(productNode),
        variants: [],
    };
}

