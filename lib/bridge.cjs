'use strict';
/* native bridge: loads the vendored win32 core and exposes two helpers.
 * the core is vendored verbatim from an off-the-shelf desktop app (ia32, N-API).
 * exports used: g(path, uid, vip, tok, firstMs, launches, campaign) -> string
 *               pwd(secret) -> string
 */
const path = require('path');

function load(file) {
  const m = { exports: {} };
  process.dlopen(m, path.join(__dirname, 'native', file));
  return m.exports;
}

module.exports = { load };
