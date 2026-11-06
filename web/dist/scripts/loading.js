/* Runs inline before the entry bundle; must not depend on React or downloaded CSS. */
(function () {
  var MAX_RETRIES = Number('__ERIDANUS_MAX_RETRIES__');
  var RETRY_DELAY_MS = Number('__ERIDANUS_RETRY_DELAY_MS__');
  if (!isFinite(MAX_RETRIES)) MAX_RETRIES = 1;
  if (!isFinite(RETRY_DELAY_MS)) RETRY_DELAY_MS = 1000;
  if (window.__ERIDANUS_ASSETS__) return;

  var pending = Object.create(null);
  var failed = false;
  var booting = true;
  var panel;
  var title;
  var description;
  var refresh;
  var mountObserver;
  var focusBeforeError;

  var style = document.createElement('style');
  style.textContent = [
    '#eridanus-assets{--asset-bg:#fff;--asset-text:#252936;--asset-muted:#626879;--asset-border:#e2e5ee;',
    'position:fixed;inset:0;z-index:2147483647;display:flex;align-items:flex-start;justify-content:center;',
    'padding:18px;box-sizing:border-box;pointer-events:none;color:var(--asset-text);font:14px/1.6 system-ui,sans-serif}',
    '#eridanus-assets[hidden]{display:none}',
    '#eridanus-assets[data-dark=true]{--asset-bg:#17191f;--asset-text:#f1f2f6;--asset-muted:#b6bdce;--asset-border:#393e4b}',
    '#eridanus-assets[data-boot=true],#eridanus-assets[data-failed=true]{align-items:center;background:var(--asset-bg)}',
    '#eridanus-assets[data-failed=true]{pointer-events:auto;background:rgba(20,24,34,.45);backdrop-filter:blur(3px)}',
    '#eridanus-assets .asset-card{display:flex;align-items:center;gap:12px;max-width:100%;box-sizing:border-box;',
    'padding:12px 20px;border:1px solid var(--asset-border);border-radius:12px;background:var(--asset-bg);',
    'box-shadow:0 8px 32px rgba(0,0,0,.12)}',
    '#eridanus-assets .asset-spinner{width:18px;height:18px;flex:none;border:2px solid var(--asset-border);',
    'border-top-color:#6274d8;border-radius:50%;animation:eridanus-asset-spin .8s linear infinite}',
    '#eridanus-assets .asset-title{margin:0;font-size:14px;font-weight:600}',
    '#eridanus-assets .asset-description{margin:6px 0 0;color:var(--asset-muted);font-size:14px}',
    '#eridanus-assets .asset-description[hidden],#eridanus-assets button[hidden]{display:none}',
    '#eridanus-assets[data-failed=true] .asset-card{display:block;width:400px;padding:28px}',
    '#eridanus-assets[data-failed=true] .asset-title{font-size:18px}',
    '#eridanus-assets[data-failed=true] .asset-spinner{display:none}',
    '#eridanus-assets button{margin-top:20px;padding:8px 18px;border:0;border-radius:8px;background:#6274d8;',
    'color:white;font:inherit;cursor:pointer}',
    '#eridanus-assets button:hover{background:#5264c9}',
    '#eridanus-assets button:focus-visible{outline:3px solid #96a2ef;outline-offset:3px}',
    '@keyframes eridanus-asset-spin{to{transform:rotate(360deg)}}',
    '@media(prefers-reduced-motion:reduce){#eridanus-assets .asset-spinner{animation:none}}',
  ].join('');
  document.head.appendChild(style);

  function mount() {
    if (!document.body || panel) return;
    panel = document.createElement('div');
    panel.id = 'eridanus-assets';
    panel.innerHTML =
      '<div class="asset-card"><span class="asset-spinner" aria-hidden="true"></span>' +
      '<div><p class="asset-title" id="eridanus-assets-title"></p>' +
      '<p class="asset-description" id="eridanus-assets-description" hidden></p>' +
      '<button type="button" hidden>刷新页面</button></div></div>';
    title = panel.querySelector('.asset-title');
    description = panel.querySelector('.asset-description');
    refresh = panel.querySelector('button');
    refresh.addEventListener('click', function () {
      window.location.reload();
    });
    document.body.appendChild(panel);
    if (mountObserver) mountObserver.disconnect();
    render();
  }

  function render() {
    if (!panel) {
      mount();
      return;
    }
    var ids = Object.keys(pending);
    var retryingId = ids.find(function (id) {
      return pending[id] && pending[id].status === 'retry';
    });
    var retryAttempt = retryingId ? pending[retryingId].attempt : 0;
    panel.hidden = !booting && !failed && ids.length === 0;
    panel.dataset.boot = String(booting);
    panel.dataset.failed = String(failed);
    // Read the app setting on each change so switching theme is respected.
    try {
      var darkSetting = localStorage.getItem('isDark');
      panel.dataset.dark = String(
        darkSetting === 'true' ||
          (darkSetting === null && window.matchMedia('(prefers-color-scheme: dark)').matches),
      );
    } catch (_) {
      panel.dataset.dark = 'false';
    }
    panel.setAttribute('role', failed ? 'alertdialog' : 'status');
    panel.setAttribute('aria-live', failed ? 'assertive' : 'polite');
    panel.setAttribute('aria-labelledby', 'eridanus-assets-title');
    if (failed) {
      panel.setAttribute('aria-modal', 'true');
      panel.setAttribute('aria-describedby', 'eridanus-assets-description');
    }
    title.textContent = failed
      ? '页面资源加载失败'
      : retryingId
        ? '加载失败，正在重试（' + retryAttempt + '/' + MAX_RETRIES + '）…'
        : booting
          ? '正在加载应用…'
          : '正在加载页面资源…';
    description.textContent = '自动重试后仍无法加载，请检查网络后刷新页面。刷新可能丢失未保存的修改。';
    description.hidden = !failed;
    refresh.hidden = !failed;
    if (failed && !focusBeforeError) {
      focusBeforeError = document.activeElement;
      refresh.focus();
    }
  }

  window.__ERIDANUS_ASSETS__ = {
    begin: function (id) {
      pending[id] = { status: 'loading', attempt: 0 };
      render();
    },
    retry: function (id, attempt) {
      pending[id] = { status: 'retry', attempt: attempt || 1 };
      render();
    },
    end: function (id) {
      delete pending[id];
      render();
    },
    fail: function (id) {
      delete pending[id];
      failed = true;
      render();
      // Keep keyboard focus in the recovery UI while the page is unusable.
      document.addEventListener('keydown', function (event) {
        if (refresh && event.key === 'Tab') {
          event.preventDefault();
          refresh.focus();
        }
      });
    },
    ready: function () {
      booting = false;
      render();
    },
  };

  // Entry scripts have no webpack loader yet. Listen before the parser fetches them.
  // webpack-owned chunks use the runtime above; never retry them a second time here.
  var entryRetries = Object.create(null);

  function retryEntryScript(script, url, id) {
    var attempts = entryRetries[id] || 0;
    if (attempts >= MAX_RETRIES) {
      window.__ERIDANUS_ASSETS__.fail(id);
      return;
    }
    attempts += 1;
    entryRetries[id] = attempts;
    window.__ERIDANUS_ASSETS__.retry(id, attempts);
    setTimeout(function () {
      var replacement = document.createElement('script');
      Array.prototype.forEach.call(script.attributes, function (attribute) {
        if (attribute.name !== 'src') replacement.setAttribute(attribute.name, attribute.value);
      });
      replacement.setAttribute('data-asset-retry', 'true');
      replacement.async = false;
      var retryUrl = new URL(url.href);
      retryUrl.searchParams.set('__asset_retry', String(Date.now()));
      replacement.src = retryUrl.href;
      replacement.onload = function () {
        window.__ERIDANUS_ASSETS__.end(id);
      };
      replacement.onerror = function () {
        retryEntryScript(replacement, retryUrl, id);
      };
      script.remove();
      document.head.appendChild(replacement);
    }, RETRY_DELAY_MS);
  }

  document.addEventListener(
    'error',
    function (event) {
      var script = event.target;
      if (
        !booting ||
        !script ||
        script.tagName !== 'SCRIPT' ||
        !script.src ||
        script.hasAttribute('data-webpack') ||
        script.hasAttribute('data-asset-retry')
      ) {
        return;
      }
      var url = new URL(script.src, window.location.href);
      // Player CDN scripts and API requests are outside application bundle recovery.
      if (url.origin !== window.location.origin || !/\/(umi|preload_helper)[^/]*\.js$/.test(url.pathname)) {
        return;
      }
      var id = 'entry:' + url.pathname;
      retryEntryScript(script, url, id);
    },
    true,
  );

  if (!document.body) {
    mountObserver = new MutationObserver(mount);
    mountObserver.observe(document.documentElement, { childList: true });
  }
  mount();
})();
