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
snEco.handle401 = function(){
  if (document.getElementById('sn-401-overlay')) return;
  const o = document.createElement('div');
  o.id = 'sn-401-overlay';
  o.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:9999;display:flex;align-items:center;justify-content:center;color:#fff;font-family:system-ui;';
  o.innerHTML = '<div style="background:#FEBF27;color:#1E1E1E;padding:32px 48px;border-radius:12px;text-align:center;max-width:480px"><div style="font-size:48px;margin-bottom:12px">🔒</div><h2 style="margin:0 0 8px;font-size:20px">Сесія закінчилась</h2><p style="margin:0 0 20px;font-size:14px">Увійдіть знов щоб продовжити.</p><button onclick="localStorage.clear();location.reload();" style="background:#1E1E1E;color:#FEBF27;border:none;padding:12px 24px;border-radius:8px;font-size:14px;font-weight:700;cursor:pointer">Увійти знову</button></div>';
  document.body.appendChild(o);
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
