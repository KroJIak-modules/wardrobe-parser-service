import { load } from 'cheerio';
import {
    isSameHost,
    looksLikeNavigationalUrl,
    looksLikeProductUrl,
    toAbsoluteUrl,
} from './url-tools.mjs';
import { findProductNode, parseJsonLdObjects } from './jsonld-tools.mjs';

export function discoverLinksFromHtml({ baseUrl, currentUrl, html }) {
    const $ = load(html || '');
    const productUrls = new Set();
    const navigationalUrls = new Set();
    const productNode = findProductNode(parseJsonLdObjects($));
    if (productNode) {
        productUrls.add(currentUrl);
    }

    $('a[href]').each((_, element) => {
        const href = $(element).attr('href');
        const absolute = toAbsoluteUrl(currentUrl || baseUrl, href);
        if (!absolute) return;
        if (!isSameHost(baseUrl, absolute)) return;
        if (!looksLikeNavigationalUrl(absolute)) return;
        if (looksLikeProductUrl(absolute)) {
            productUrls.add(absolute);
            return;
        }
        navigationalUrls.add(absolute);
    });

    return {
        productUrls: [...productUrls],
        navigationalUrls: [...navigationalUrls],
    };
}
