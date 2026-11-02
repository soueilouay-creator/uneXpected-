import { extname, resolve, sep } from 'node:path';

const MIME_TYPES = Object.freeze({
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png'
});

export function resolveMobileAsset(urlPath, publicRoot) {
  if (typeof urlPath !== 'string' || !urlPath.startsWith('/mobile')) return null;
  let decoded;
  try { decoded = decodeURIComponent(urlPath); } catch { return null; }
  if (decoded !== '/mobile' && !decoded.startsWith('/mobile/')) return null;
  const relative = decoded.replace(/^\/mobile\/?/, '') || 'index.html';
  const mobileRoot = resolve(publicRoot, 'mobile');
  const filePath = resolve(mobileRoot, relative);
  if (filePath !== mobileRoot && !filePath.startsWith(mobileRoot + sep)) return null;
  const contentType = MIME_TYPES[extname(filePath).toLowerCase()];
  if (!contentType) return null;
  return {
    filePath,
    contentType,
    cacheControl: relative === 'index.html' || relative === 'sw.js' ? 'no-cache' : 'public, max-age=300'
  };
}
