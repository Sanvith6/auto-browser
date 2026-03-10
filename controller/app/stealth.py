"""Browser fingerprint masking — init scripts applied to every new page."""
from __future__ import annotations

# Injected before any page script runs. Removes automation signals,
# mocks realistic browser properties, adds minor canvas/WebGL noise.
STEALTH_INIT_SCRIPT = r"""
() => {
  // Remove webdriver flag
  try {
    Object.defineProperty(navigator, 'webdriver', {
      get: () => undefined, configurable: true,
    });
  } catch (_) {}

  // Chrome runtime object (many sites check for this)
  if (!window.chrome) {
    window.chrome = {
      runtime: {
        onMessage: { addListener: () => {}, removeListener: () => {} },
        connect: () => ({ onDisconnect: { addListener: () => {} }, postMessage: () => {} }),
        sendMessage: () => {},
        id: undefined,
      },
      loadTimes: () => ({}),
      csi: () => ({}),
      app: { isInstalled: false },
    };
  }

  // Realistic navigator.plugins (headless has none by default)
  try {
    const plugins = [
      { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
      { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
    ];
    const arr = { length: plugins.length, refresh: () => {}, item: (i) => plugins[i], namedItem: (n) => plugins.find(p => p.name === n) || null };
    plugins.forEach((p, i) => { arr[i] = p; });
    Object.setPrototypeOf(arr, PluginArray.prototype);
    Object.defineProperty(navigator, 'plugins', { get: () => arr });
  } catch (_) {}

  // Languages
  try {
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
  } catch (_) {}

  // Permissions API — notifications permission
  try {
    const origQuery = window.Permissions.prototype.query;
    window.Permissions.prototype.query = function(params) {
      if (params.name === 'notifications') {
        return Promise.resolve({ state: Notification.permission, onchange: null });
      }
      return origQuery.call(this, params);
    };
  } catch (_) {}

  // Canvas fingerprint noise (tiny, invisible pixel-level variation)
  try {
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type, quality) {
      const ctx = this.getContext('2d');
      if (ctx && this.width > 0 && this.height > 0) {
        try {
          const img = ctx.getImageData(0, 0, 1, 1);
          img.data[0] ^= 1;
          ctx.putImageData(img, 0, 0);
          const result = origToDataURL.call(this, type, quality);
          img.data[0] ^= 1;
          ctx.putImageData(img, 0, 0);
          return result;
        } catch (_) {}
      }
      return origToDataURL.call(this, type, quality);
    };
  } catch (_) {}

  // WebGL vendor / renderer — realistic Intel values
  try {
    const patchWebGL = (ctx) => {
      const orig = ctx.getParameter.bind(ctx.__proto__);
      ctx.__proto__.getParameter = function(p) {
        if (p === 37445) return 'Intel Inc.';
        if (p === 37446) return 'Intel Iris OpenGL Engine';
        return orig(p);
      };
    };
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl') || c.getContext('experimental-webgl');
    if (gl) patchWebGL(gl);
    const gl2 = c.getContext('webgl2');
    if (gl2) patchWebGL(gl2);
  } catch (_) {}

  // Hardware concurrency + device memory (realistic desktop values)
  try {
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
  } catch (_) {}
  try {
    Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
  } catch (_) {}

  // Screen dimensions consistency
  try {
    Object.defineProperty(screen, 'colorDepth', { get: () => 24 });
    Object.defineProperty(screen, 'pixelDepth', { get: () => 24 });
  } catch (_) {}
}
"""

# Extract structured post data from a feed-like page
EXTRACT_POSTS_SCRIPT = r"""
(limit) => {
  const candidates = [];
  const seen = new Set();
  const els = document.querySelectorAll(
    'article, [role="article"], [data-testid*="tweet"], ' +
    '[data-testid*="post"], [class*="post-content"], ' +
    '[class*="feed-item"], [class*="timeline-item"]'
  );
  for (const el of els) {
    const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
    if (text.length < 20 || seen.has(text.slice(0, 100))) continue;
    seen.add(text.slice(0, 100));
    const rect = el.getBoundingClientRect();
    if (rect.width === 0) continue;
    const links = [...el.querySelectorAll('a[href]')]
      .map(a => a.href).filter(h => h && !h.startsWith('javascript'));
    const imgs = [...el.querySelectorAll('img[src]')].map(i => i.src).slice(0, 3);
    candidates.push({
      text: text.slice(0, 600),
      links: links.slice(0, 5),
      images: imgs,
      tag: el.tagName.toLowerCase(),
      y_position: Math.round(rect.top + window.scrollY),
    });
    if (candidates.length >= limit) break;
  }
  return candidates;
}
"""

# Extract profile info from any social media profile page
EXTRACT_PROFILE_SCRIPT = r"""
() => {
  function first(selectors) {
    for (const s of selectors) {
      const el = document.querySelector(s);
      const text = el ? (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim() : null;
      if (text && text.length > 0) return text.slice(0, 300);
    }
    return null;
  }
  function findCount(keyword) {
    for (const el of document.querySelectorAll('a, span, div')) {
      const text = (el.innerText || '').toLowerCase();
      if (text.includes(keyword) && /[\d,]+/.test(text)) {
        const m = text.match(/([\d,.]+\s*[kmb]?)/i);
        return m ? m[0].trim() : null;
      }
    }
    return null;
  }
  return {
    page_title: document.title,
    url: window.location.href,
    username: first(['[data-testid="UserName"]', '.username', 'h1', '[class*="username"]']),
    display_name: first(['[data-testid="UserName"] span', '[class*="display-name"]', '[class*="displayName"]']),
    bio: first(['[data-testid="UserDescription"]', '[class*="bio"]', '[class*="about"]', '[class*="description"]']),
    followers: findCount('follower'),
    following: findCount('following'),
    post_count: findCount('post') || findCount('tweet') || findCount('video'),
    avatar_url: document.querySelector(
      'img[src*="profile_image"], img[src*="avatar"], img[class*="avatar"], img[class*="profile"]'
    )?.src || null,
  };
}
"""

# Smooth scroll simulation script (more human than window.scrollBy)
SMOOTH_SCROLL_SCRIPT = r"""
(deltaY) => {
  return new Promise((resolve) => {
    const step = Math.sign(deltaY) * Math.min(Math.abs(deltaY), 80);
    let remaining = Math.abs(deltaY);
    function tick() {
      if (remaining <= 0) { resolve(); return; }
      const amount = Math.min(remaining, Math.abs(step));
      window.scrollBy({ top: Math.sign(deltaY) * amount, behavior: 'auto' });
      remaining -= amount;
      setTimeout(tick, 16 + Math.random() * 8);
    }
    tick();
  });
}
"""


async def apply_stealth(page: object) -> None:
    """Inject stealth init script into a page. Call before any navigation."""
    await page.add_init_script(STEALTH_INIT_SCRIPT)
