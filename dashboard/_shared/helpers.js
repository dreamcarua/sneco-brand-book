// snEco shared dashboard helpers v2.78.99
// Eliminates ~3000 LoC duplicate across 7 dashboards
// Import via: <script src="../_shared/helpers.js"></script>

window.snEco = window.snEco || {};

// === Format helpers ===
snEco.escapeHtml = function(s){
  return String(s||'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
};

snEco.fmtNumber = function(n){
  return new Intl.NumberFormat('uk-UA').format(Math.round(n || 0));
};

snEco.fmtMoney = function(n){
  return snEco.fmtNumber(n) + ' ₴';
};

snEco.fmtDate = function(d){
  if (!d) return '—';
  const dt = (d instanceof Date) ? d : new Date(d);
  return dt.toLocaleDateString('uk-UA', {day:'2-digit', month:'2-digit', year:'numeric'});
};

snEco.fmtPct = function(n, decimals=1){
  return (n || 0).toFixed(decimals) + '%';
};

// === Fetch state banner (loading/success/error) ===
snEco.showFetchBanner = function(text, type){
  let banner = document.getElementById('fetch-state-banner');
  if (!type) { if (banner) banner.remove(); return; }
  if (!banner) {
    banner = document.createElement('div');
    banner.id = 'fetch-state-banner';
    banner.style.cssText = 'position:fixed;top:54px;left:0;right:0;z-index:50;padding:10px 18px;text-align:center;font-size:13px;font-weight:600;box-shadow:0 2px 8px rgba(0,0,0,0.08);transition:all 0.3s';
    document.body.appendChild(banner);
  }
  const styles = {
    loading: 'background:rgba(254,191,39,0.95);color:#1E1E1E',
    error:   'background:rgba(239,68,68,0.95);color:#fff',
    empty:   'background:rgba(150,193,31,0.95);color:#1E1E1E'
  };
  banner.style.cssText += ';' + (styles[type] || styles.loading);
  banner.innerHTML = String(text || '').replace(/<script/gi, '&lt;script');
};

// === 401 handler (session expired overlay) ===
// v2.78.115: показує Google Sign-In + OTP fallback ПРЯМО у overlay (без зайвих reload)
snEco.handle401 = function(block){
  if (document.getElementById('sn-401-overlay')) return;
  // BLOCK auto-detect якщо не passed (читаємо з window або URL)
  if (!block) {
    block = window._snAuthBlock ||
            (location.pathname.includes('customer-360') ? 'customer-dashboard' :
             location.pathname.includes('finance') ? 'finance-dashboard' :
             location.pathname.includes('procurement') ? 'procurement-dashboard' :
             location.pathname.includes('inventory') ? 'inventory-dashboard' :
             location.pathname.includes('production') ? 'production-dashboard' :
             location.pathname.includes('attribution') ? 'attribution-dashboard' :
             'dashboard');
  }
  const o = document.createElement('div');
  o.id = 'sn-401-overlay';
  o.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:9999;display:flex;align-items:center;justify-content:center;color:#fff;font-family:system-ui;padding:20px';
  o.innerHTML = `
    <div style="background:#FEBF27;color:#1E1E1E;padding:30px 32px;border-radius:12px;text-align:center;max-width:420px;box-shadow:0 12px 48px rgba(0,0,0,0.5)">
      <div style="font-size:42px;margin-bottom:8px">🔒</div>
      <h2 style="margin:0 0 6px;font-size:19px">Сесія закінчилась</h2>
      <p style="margin:0 0 16px;font-size:13px;line-height:1.5;color:#3a3a3a">Увійдіть знову — через Google (1 клік) або email-OTP</p>
      <div id="sn401-google-btn" style="display:flex;justify-content:center;margin-bottom:12px;min-height:42px"></div>
      <div style="font-size:11px;color:#5a5a5a;margin:8px 0">— або —</div>
      <button onclick="localStorage.removeItem('snEco-jwt-${block}'); location.reload();" style="background:#1E1E1E;color:#FEBF27;border:none;padding:10px 20px;border-radius:8px;font-size:13px;font-weight:700;cursor:pointer;width:100%">Увійти через email-OTP</button>
      <div id="sn401-msg" style="font-size:12px;color:#dc2626;margin-top:10px;min-height:14px"></div>
    </div>`;
  document.body.appendChild(o);
  // Запуск Google Sign-In у overlay
  let attempts = 0;
  function tryStartGoogle() {
    attempts++;
    if (window.SnecoAuth) {
      const gBtn = document.getElementById('sn401-google-btn');
      const msg = document.getElementById('sn401-msg');
      window.SnecoAuth.signInWithGoogle(block, gBtn,
        (j) => {
          localStorage.setItem('snEco-jwt-' + block,
            JSON.stringify({token: j.token, email: j.email, exp: j.exp}));
          location.reload();
        },
        (err) => { if (msg) msg.textContent = err; }
      );
    } else if (attempts < 25) {
      setTimeout(tryStartGoogle, 200);  // wait for auth-google.js
    } else {
      const msg = document.getElementById('sn401-msg');
      if (msg) msg.textContent = 'Google auth недоступний — використайте OTP';
    }
  }
  tryStartGoogle();
};

// === Fetch wrapper з error handling + 401 ===
snEco.fetchJSON = async function(url, opts){
  opts = opts || {};
  opts.headers = opts.headers || {};
  if (!opts.headers['Content-Type']) opts.headers['Content-Type'] = 'application/json';
  if (snEco.token) opts.headers['Authorization'] = 'Bearer ' + snEco.token;
  const r = await fetch(url, opts);
  if (r.status === 401) {
    snEco.handle401();
    throw new Error('401 unauthorized');
  }
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
};

// === Report client error to Worker ===
snEco.reportError = function(err, context){
  context = context || {};
  fetch('https://sneco-auth.vg-ab6.workers.dev/api/errors/log', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      severity: context.severity || 'error',
      source: context.source || 'dashboard',
      message: err.message || String(err),
      stack: err.stack || null,
      url: location.href,
      context: context,
    }),
  }).catch(() => {});
};

// === Global error → reportError ===
window.addEventListener('error', e => {
  snEco.reportError(e.error || new Error(e.message), {source:'dashboard-window-error', filename:e.filename, line:e.lineno});
});
window.addEventListener('unhandledrejection', e => {
  snEco.reportError(e.reason || new Error('unhandled rejection'), {source:'dashboard-unhandled'});
});

console.log('[snEco helpers v2.78.99] loaded');
