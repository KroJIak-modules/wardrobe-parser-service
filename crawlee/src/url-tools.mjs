export function normalizeBaseUrl(rawUrl) {
    const parsed = new URL(String(rawUrl || '').trim());
    return `${parsed.protocol}//${parsed.host}`;
}

export function toAbsoluteUrl(baseUrl, href) {
    try {
        if (!href) return null;
        const normalized = String(href).trim();
        if (!normalized || normalized.startsWith('#')) return null;
        if (normalized.startsWith('javascript:') || normalized.startsWith('mailto:') || normalized.startsWith('tel:')) {
            return null;
        }
        return new URL(normalized, baseUrl).toString();
    } catch {
        return null;
    }
}

export function isSameHost(baseUrl, candidateUrl) {
    try {
        return new URL(baseUrl).host === new URL(candidateUrl).host;
    } catch {
        return false;
    }
}

export function normalizeProductHandle(url) {
    try {
        const parsed = new URL(url);
        const markerIndex = parsed.pathname.toLowerCase().indexOf('/product');
        if (markerIndex >= 0) {
            const tail = parsed.pathname.slice(markerIndex + 1);
            const parts = tail.split('/').filter(Boolean);
            return (parts[parts.length - 1] || '').trim();
        }
        const parts = parsed.pathname.split('/').filter(Boolean);
        return (parts[parts.length - 1] || parsed.host).trim();
    } catch {
        return '';
    }
}

export function looksLikeProductUrl(candidateUrl) {
    try {
        const pathname = new URL(candidateUrl).pathname.toLowerCase();
        const productPatterns = [
            '/product/',
            '/products/',
            '/shop/',
            '/item/',
            '/items/',
            '/p/'
        ];
        return productPatterns.some((pattern) => pathname.includes(pattern));
    } catch {
        return false;
    }
}

export function looksLikeNavigationalUrl(candidateUrl) {
    try {
        const pathname = new URL(candidateUrl).pathname.toLowerCase();
        const blockedExt = ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg', '.pdf', '.zip', '.css', '.js', '.xml', '.json'];
        if (blockedExt.some((ext) => pathname.endsWith(ext))) return false;
        const blockedPaths = ['/cart', '/checkout', '/account', '/search?', '/login'];
        if (blockedPaths.some((item) => pathname.includes(item))) return false;
        return true;
    } catch {
        return false;
    }
}

