export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function toArray(value) {
  if (!value) return [];
  return Array.isArray(value) ? value : [value];
}

export function safeHostFromUrl(url) {
  try {
    return new URL(url).hostname.toLowerCase();
  } catch {
    return 'unknown-host';
  }
}

export function sanitizeFileStem(value) {
  return String(value || 'output')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'output';
}
