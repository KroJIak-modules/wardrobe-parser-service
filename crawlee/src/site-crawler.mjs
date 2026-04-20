import { BasicCrawler, RequestQueue } from 'crawlee';
import { discoverLinksFromHtml } from './link-discovery.mjs';
import { parseProductPreviewFromHtml } from './product-parser.mjs';
import { normalizeBaseUrl } from './url-tools.mjs';

class CrawlState {
    constructor(baseUrl, maxProducts) {
        this.baseUrl = baseUrl;
        this.maxProducts = maxProducts;
        this.discoveredProductUrls = new Set();
        this.visitedDiscoveryUrls = new Set();
        this.enqueuedDiscoveryUrls = new Set();
        this.previews = [];
        this.errors = [];
        this.warnings = [];
        this.http429Count = 0;
        this.http5xxCount = 0;
    }

    canCollectMoreProducts() {
        return this.discoveredProductUrls.size < this.maxProducts;
    }

    addProductUrl(url) {
        if (!this.canCollectMoreProducts()) return;
        this.discoveredProductUrls.add(url);
    }
}

export class SiteCrawler {
    constructor(options) {
        this.options = options;
        this.baseUrl = normalizeBaseUrl(options.baseUrl);
        this.state = new CrawlState(this.baseUrl, options.maxProducts);
    }

    async run() {
        await this.runDiscoveryPass();
        await this.runProductPass();
        return this.buildResult();
    }

    async runDiscoveryPass() {
        const queue = await RequestQueue.open(`crawlee-discovery-${Date.now()}`);
        this.state.enqueuedDiscoveryUrls.add(this.baseUrl);
        await queue.addRequest({
            url: this.baseUrl,
            uniqueKey: `${this.baseUrl}|discovery|root`,
            userData: { label: 'DISCOVERY_PAGE', depth: 0 },
        });

        const crawler = new BasicCrawler({
            requestQueue: queue,
            maxConcurrency: this.options.maxConcurrency,
            maxRequestRetries: this.options.maxRetries,
            requestHandlerTimeoutSecs: Math.ceil(this.options.timeoutMs / 1000),
            requestHandler: async ({ request, sendRequest }) => {
                const url = request.url;
                const depth = Number(request.userData?.depth || 0);
                if (this.state.visitedDiscoveryUrls.has(url)) return;
                this.state.visitedDiscoveryUrls.add(url);

                const response = await sendRequest({
                    url,
                    method: 'GET',
                    responseType: 'text',
                    timeout: { request: this.options.timeoutMs },
                });
                const status = response.statusCode || 0;
                if (status === 429) this.state.http429Count += 1;
                if (status >= 500) this.state.http5xxCount += 1;
                if (status < 200 || status >= 300) {
                    this.state.errors.push(`DISCOVERY_PAGE ${url}: HTTP ${status}`);
                    return;
                }

                const html = String(response.body || '');
                const links = discoverLinksFromHtml({
                    baseUrl: this.baseUrl,
                    currentUrl: url,
                    html,
                });

                for (const productUrl of links.productUrls) {
                    this.state.addProductUrl(productUrl);
                    if (!this.state.canCollectMoreProducts()) break;
                }

                if (depth >= this.options.maxDiscoveryDepth) return;
                if (this.state.visitedDiscoveryUrls.size >= this.options.maxDiscoveryPages) return;
                if (!this.state.canCollectMoreProducts()) return;

                for (const navUrl of links.navigationalUrls) {
                    if (this.state.visitedDiscoveryUrls.has(navUrl)) continue;
                    if (this.state.enqueuedDiscoveryUrls.has(navUrl)) continue;
                    if (this.state.enqueuedDiscoveryUrls.size >= this.options.maxDiscoveryPages) break;
                    this.state.enqueuedDiscoveryUrls.add(navUrl);
                    await queue.addRequest({
                        url: navUrl,
                        uniqueKey: `${this.baseUrl}|discovery|${navUrl}`,
                        userData: { label: 'DISCOVERY_PAGE', depth: depth + 1 },
                    });
                }
            },
        });

        await crawler.run();
    }

    async runProductPass() {
        const queue = await RequestQueue.open(`crawlee-products-${Date.now()}`);
        const productUrls = [...this.state.discoveredProductUrls].slice(0, this.options.maxProducts);
        for (const productUrl of productUrls) {
            await queue.addRequest({
                url: productUrl,
                uniqueKey: `${this.baseUrl}|product|${productUrl}`,
                userData: { label: 'PRODUCT_PAGE' },
            });
        }

        const crawler = new BasicCrawler({
            requestQueue: queue,
            maxConcurrency: this.options.maxConcurrency,
            maxRequestRetries: this.options.maxRetries,
            requestHandlerTimeoutSecs: Math.ceil(this.options.timeoutMs / 1000),
            requestHandler: async ({ request, sendRequest }) => {
                const productUrl = request.url;
                const response = await sendRequest({
                    url: productUrl,
                    method: 'GET',
                    responseType: 'text',
                    timeout: { request: this.options.timeoutMs },
                });
                const status = response.statusCode || 0;
                if (status === 429) this.state.http429Count += 1;
                if (status >= 500) this.state.http5xxCount += 1;
                if (status < 200 || status >= 300) {
                    this.state.errors.push(`PRODUCT_PAGE ${productUrl}: HTTP ${status}`);
                    return;
                }
                const html = String(response.body || '');
                const preview = parseProductPreviewFromHtml({
                    productUrl,
                    html,
                });
                this.state.previews.push(preview);
            },
        });

        await crawler.run();
    }

    buildResult() {
        const attempted = this.state.discoveredProductUrls.size;
        const succeeded = this.state.previews.length;
        const failed = Math.max(0, attempted - succeeded);
        if (attempted === 0) {
            this.state.warnings.push('no product urls discovered in crawlee crawl');
        }
        if (this.state.visitedDiscoveryUrls.size >= this.options.maxDiscoveryPages) {
            this.state.warnings.push(`discovery limit reached: ${this.options.maxDiscoveryPages} pages`);
        }

        return {
            base_url: this.baseUrl,
            discovery_mode: 'crawlee',
            product_urls_found: attempted,
            products_fetch_attempted: attempted,
            products_fetch_succeeded: succeeded,
            products_fetch_failed: failed,
            http_429_count: this.state.http429Count,
            http_5xx_count: this.state.http5xxCount,
            warnings: this.state.warnings,
            error_details: this.state.errors.slice(0, this.options.errorDetailsLimit),
            previews: this.state.previews,
        };
    }
}
