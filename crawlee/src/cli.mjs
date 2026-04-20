function parseArgs(argv) {
    const args = {};
    for (let i = 0; i < argv.length; i += 1) {
        const key = argv[i];
        if (!key.startsWith('--')) continue;
        args[key.slice(2)] = argv[i + 1];
        i += 1;
    }
    return args;
}

function requiredString(value, field) {
    const normalized = String(value || '').trim();
    if (!normalized) throw new Error(`Missing required argument --${field}`);
    return normalized;
}

function intArg(value, fallback, min = 1) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.max(min, Math.floor(parsed));
}

async function main() {
    process.env.CRAWLEE_LOG_LEVEL = process.env.CRAWLEE_LOG_LEVEL || 'ERROR';
    process.env.CRAWLEE_STORAGE_DIR = process.env.CRAWLEE_STORAGE_DIR || '/tmp/wardrobe-crawlee-storage';
    const { SiteCrawler } = await import('./site-crawler.mjs');
    const raw = parseArgs(process.argv.slice(2));
    const baseUrl = requiredString(raw['base-url'], 'base-url');
    const options = {
        baseUrl,
        maxProducts: intArg(raw['max-products'], 5000),
        timeoutMs: intArg(raw['timeout-ms'], 20000),
        maxDiscoveryPages: intArg(raw['max-discovery-pages'], 80),
        maxDiscoveryDepth: intArg(raw['max-discovery-depth'], 3),
        maxConcurrency: intArg(raw['max-concurrency'], 8),
        maxRetries: intArg(raw['max-retries'], 1, 0),
        errorDetailsLimit: intArg(raw['error-details-limit'], 200),
    };

    const crawler = new SiteCrawler(options);
    const result = await crawler.run();
    process.stdout.write(`${JSON.stringify(result)}\n`);
}

main().catch((error) => {
    process.stderr.write(`crawlee-cli error: ${String(error?.message || error)}\n`);
    process.exit(1);
});
