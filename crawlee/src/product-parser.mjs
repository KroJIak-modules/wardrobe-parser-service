import { load } from 'cheerio';
import { buildProductFromJsonLd, findProductNode, parseJsonLdObjects } from './jsonld-tools.mjs';
import { normalizeProductHandle } from './url-tools.mjs';

function extractMetaContent($, selector) {
    const value = $(selector).attr('content');
    return value ? String(value).trim() : null;
}

function toNullableText(value) {
    const normalized = String(value ?? '').trim();
    return normalized || null;
}

export function parseProductPreviewFromHtml({ productUrl, html }) {
    const $ = load(html || '');
    const jsonLdObjects = parseJsonLdObjects($);
    const productNode = findProductNode(jsonLdObjects);
    const fromJsonLd = productNode ? buildProductFromJsonLd(productNode) : null;

    const fallbackTitle = toNullableText($('h1').first().text()) || extractMetaContent($, 'meta[property="og:title"]');
    const fallbackDescription = extractMetaContent($, 'meta[name="description"]')
        || extractMetaContent($, 'meta[property="og:description"]');
    const fallbackImage = extractMetaContent($, 'meta[property="og:image"]');

    const imageUrls = fromJsonLd?.image_urls?.length
        ? fromJsonLd.image_urls
        : (fallbackImage ? [fallbackImage] : []);

    return {
        product_url: productUrl,
        handle: normalizeProductHandle(productUrl) || 'unknown',
        title: fromJsonLd?.title || fallbackTitle,
        description: fromJsonLd?.description || fallbackDescription,
        vendor: fromJsonLd?.vendor || null,
        product_type: fromJsonLd?.product_type || null,
        price: fromJsonLd?.price || null,
        currency: fromJsonLd?.currency || null,
        image_urls: imageUrls,
        available: fromJsonLd?.available ?? true,
        variants: fromJsonLd?.variants || [],
        payload_source: 'crawlee',
    };
}
