"""Browser-side JavaScript constants used by BrowserManager for page observation."""
from __future__ import annotations

# Injected before every page load via add_init_script().
# Removes automation signals, mocks realistic browser properties.
STEALTH_INIT_SCRIPT = r"""
() => {
  // Remove webdriver flag
  try {
    Object.defineProperty(navigator, 'webdriver', {
      get: () => undefined, configurable: true,
    });
  } catch (_) {}

  // Chrome runtime object (many sites check for this)
  if (\!window.chrome) {
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

  // Permissions API patch
  try {
    const origQuery = window.Permissions.prototype.query;
    window.Permissions.prototype.query = function(params) {
      if (params.name === 'notifications') {
        return Promise.resolve({ state: Notification.permission, onchange: null });
      }
      return origQuery.call(this, params);
    };
  } catch (_) {}

  // Canvas fingerprint noise
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
    const patchGL = (proto) => {
      const orig = proto.getParameter;
      proto.getParameter = function(p) {
        if (p === 37445) return 'Intel Inc.';
        if (p === 37446) return 'Intel Iris OpenGL Engine';
        return orig.call(this, p);
      };
    };
    patchGL(WebGLRenderingContext.prototype);
    if (typeof WebGL2RenderingContext \!== 'undefined') patchGL(WebGL2RenderingContext.prototype);
  } catch (_) {}

  // Realistic hardware values
  try { Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 }); } catch (_) {}
  try { Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 }); } catch (_) {}
  try { Object.defineProperty(screen, 'colorDepth', { get: () => 24 }); } catch (_) {}
}
"""

INTERACTABLES_SCRIPT = r"""
(limit) => {
  function isVisible(el) {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  }

  function getLabel(el) {
    const raw = el.getAttribute('aria-label')
      || el.getAttribute('placeholder')
      || el.innerText
      || el.value
      || el.getAttribute('name')
      || el.id
      || el.href
      || '';
    return String(raw).replace(/\s+/g, ' ').trim().slice(0, 160);
  }

  const selector = [
    'a',
    'button',
    'input',
    'textarea',
    'select',
    '[role="button"]',
    '[role="link"]',
    '[role="textbox"]',
    '[contenteditable="true"]',
    '[tabindex]'
  ].join(',');

  const out = [];
  for (const el of document.querySelectorAll(selector)) {
    if (!isVisible(el) || el.closest('[aria-hidden="true"]')) continue;
    if (!el.dataset.operatorId) {
      el.dataset.operatorId = `op-${Math.random().toString(36).slice(2, 10)}`;
    }
    const rect = el.getBoundingClientRect();
    out.push({
      element_id: el.dataset.operatorId,
      selector_hint: `[data-operator-id="${el.dataset.operatorId}"]`,
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type'),
      role: el.getAttribute('role') || el.tagName.toLowerCase(),
      label: getLabel(el),
      disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true'),
      href: el.href || null,
      bbox: {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height)
      }
    });
    if (out.length >= limit) break;
  }
  return out;
}
"""

ACTIVE_ELEMENT_SCRIPT = r"""
() => {
  const el = document.activeElement;
  if (!el) return null;
  return {
    tag: el.tagName.toLowerCase(),
    element_id: el.dataset?.operatorId || null,
    name: el.getAttribute('name'),
    id: el.id || null,
    label: (el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.innerText || el.value || '').toString().replace(/\s+/g, ' ').trim().slice(0, 120)
  };
}
"""

PAGE_SUMMARY_SCRIPT = r"""
(textLimit) => {
  const squash = (value, maxLength = textLimit) =>
    String(value || '').replace(/\s+/g, ' ').trim().slice(0, maxLength);

  const headings = Array.from(document.querySelectorAll('h1,h2,h3'))
    .slice(0, 8)
    .map((el) => ({
      level: el.tagName.toLowerCase(),
      text: squash(el.innerText, 160)
    }))
    .filter((item) => item.text);

  const forms = Array.from(document.forms)
    .slice(0, 3)
    .map((form) => ({
      action: form.getAttribute('action') || null,
      method: (form.getAttribute('method') || 'get').toLowerCase(),
      fields: Array.from(form.querySelectorAll('input, textarea, select, button'))
        .slice(0, 8)
        .map((field) => ({
          tag: field.tagName.toLowerCase(),
          type: field.getAttribute('type') || null,
          name: field.getAttribute('name') || null,
          label: squash(
            field.getAttribute('aria-label')
              || field.getAttribute('placeholder')
              || field.innerText
              || field.value
              || field.getAttribute('name')
              || field.id,
            80
          ),
          disabled: Boolean(field.disabled || field.getAttribute('aria-disabled') === 'true')
        }))
    }));

  return {
    text_excerpt: squash(document.body?.innerText || '', textLimit),
    dom_outline: {
      headings,
      forms,
      counts: {
        links: document.querySelectorAll('a').length,
        buttons: document.querySelectorAll('button, [role="button"]').length,
        inputs: document.querySelectorAll('input, textarea, select').length,
        forms: document.forms.length
      }
    }
  };
}
"""

# Feed/profile extraction helpers
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

# Social interaction scripts — find and click engagement buttons
FIND_LIKE_BUTTON_SCRIPT = r"""
(postIndex) => {
  const likeSelectors = [
    '[data-testid="like"]',
    '[aria-label*="like" i]:not([aria-pressed="true"])',
    '[aria-label*="heart" i]:not([aria-pressed="true"])',
    '[aria-label*="love" i]:not([aria-pressed="true"])',
    'button[class*="like"]:not([class*="liked"])',
    'button[class*="heart"]',
    '[role="button"][class*="like"]',
  ];
  const allButtons = [];
  for (const sel of likeSelectors) {
    const els = [...document.querySelectorAll(sel)];
    for (const el of els) {
      const rect = el.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        allButtons.push({
          selector: sel,
          x: Math.round(rect.x + rect.width / 2),
          y: Math.round(rect.y + rect.height / 2),
          label: (el.getAttribute('aria-label') || el.innerText || '').trim().slice(0, 80),
        });
      }
    }
  }
  const target = allButtons[postIndex] || allButtons[0] || null;
  return target;
}
"""

FIND_FOLLOW_BUTTON_SCRIPT = r"""
() => {
  const selectors = [
    '[data-testid="followButton"]',
    '[aria-label*="follow" i]:not([aria-label*="unfollow" i])',
    'button:not([class*="unfollow"]):not([class*="following"])',
  ];
  for (const sel of selectors) {
    const els = [...document.querySelectorAll(sel)];
    for (const el of els) {
      const text = (el.innerText || el.getAttribute('aria-label') || '').toLowerCase();
      if (!text.includes('follow')) continue;
      if (text.includes('unfollow') || text.includes('following')) continue;
      const rect = el.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        return {
          selector: sel,
          x: Math.round(rect.x + rect.width / 2),
          y: Math.round(rect.y + rect.height / 2),
          label: (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 80),
        };
      }
    }
  }
  return null;
}
"""

FIND_SEARCH_INPUT_SCRIPT = r"""
() => {
  const selectors = [
    '[data-testid="SearchBox_Search_Input"]',
    'input[type="search"]',
    'input[name="q"]',
    '[aria-label*="search" i]',
    '[placeholder*="search" i]',
    'input[role="searchbox"]',
    '[role="searchbox"]',
    'input[type="text"][name*="search"]',
  ];
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el) {
      const rect = el.getBoundingClientRect();
      if (rect.width > 0) return sel;
    }
  }
  return null;
}
"""

async def apply_stealth(page: object) -> None:
    """Inject stealth init script into a page before any navigation."""
    await page.add_init_script(STEALTH_INIT_SCRIPT)
