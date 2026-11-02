import test from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { resolveMobileAsset } from '../mobile-assets.mjs';

test('resolves the mobile app entry document', () => {
  const asset = resolveMobileAsset('/mobile/', '/srv/app/public');
  assert.equal(asset.filePath, resolve('/srv/app/public/mobile/index.html'));
  assert.match(asset.contentType, /text\/html/);
  assert.equal(asset.cacheControl, 'no-cache');
});
test('resolves a PWA manifest with its correct MIME type', () => {
  const asset = resolveMobileAsset('/mobile/manifest.webmanifest', '/srv/app/public');
  assert.match(asset.contentType, /manifest\+json/);
});
test('resolves role registry and service worker resources', () => {
  assert.match(resolveMobileAsset('/mobile/agents.json','/app/public').contentType,/application\/json/);
  assert.match(resolveMobileAsset('/mobile/sw.js','/app/public').contentType,/javascript/);
});
test('rejects encoded traversal and malformed paths', () => {
  assert.equal(resolveMobileAsset('/mobile/%2e%2e/server.js','/app/public'),null);
  assert.equal(resolveMobileAsset('/mobile/../../server.js','/app/public'),null);
  assert.equal(resolveMobileAsset('/mobile/%ZZ','/app/public'),null);
});
test('rejects non-mobile paths and unknown file extensions', () => {
  assert.equal(resolveMobileAsset('/server.js','/app/public'),null);
  assert.equal(resolveMobileAsset('/mobile/secrets.env','/app/public'),null);
});
