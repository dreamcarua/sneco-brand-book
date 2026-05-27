// v2.78.35 (Богдан): спільний Google Sign-In helper для всіх snEco dashboards.
// Адаптовано з abrisart auth-google.js.
//
// API:
//   window.SnecoAuth.signInWithGoogle(block, container, onSuccess, onError)
//     - block: 'customer-dashboard' | 'finance-dashboard' | 'dashboard' | 'inventory-dashboard'
//              | 'production-dashboard' | 'procurement-dashboard' | 'hr' | 'prices' | 'admin'
//     - container: HTMLElement куди render GIS кнопку
//     - onSuccess({token, email, exp, name, picture, isAdmin})
//     - onError(message)
//
// Flow:
//   1) Завантажуємо https://accounts.google.com/gsi/client (one-time)
//   2) GET /api/auth/config → дізнаємось GOOGLE_CLIENT_ID
//   3) google.accounts.id.initialize({ client_id, callback })
//   4) renderButton + One-Tap prompt
//   5) на колбек — POST /api/auth/google { id_token, block } → JWT (30 діб)
(function(){
  const WORKER = 'https://sneco-auth.vg-ab6.workers.dev';
  let _gisReady = null;
  let _config = null;

  function loadGIS() {
    if (_gisReady) return _gisReady;
    _gisReady = new Promise((resolve, reject) => {
      if (window.google && window.google.accounts && window.google.accounts.id) return resolve();
      const s = document.createElement('script');
      s.src = 'https://accounts.google.com/gsi/client';
      s.async = true; s.defer = true;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error('Failed to load Google Identity Services'));
      document.head.appendChild(s);
    });
    return _gisReady;
  }

  async function getConfig() {
    if (_config) return _config;
    const r = await fetch(WORKER + '/api/auth/config', { method: 'POST', headers: {'Content-Type':'application/json'}, body: '{}' });
    if (!r.ok) throw new Error('config_unreachable');
    _config = await r.json();
    if (!_config.google_client_id) throw new Error('GOOGLE_CLIENT_ID не налаштований у Worker');
    return _config;
  }

  async function signInWithGoogle(block, container, onSuccess, onError) {
    try {
      await loadGIS();
      const cfg = await getConfig();
      window.google.accounts.id.initialize({
        client_id: cfg.google_client_id,
        callback: async (response) => {
          if (!response.credential) { onError && onError('Google не повернув токен'); return; }
          try {
            const r = await fetch(WORKER + '/api/auth/google', {
              method: 'POST',
              headers: {'Content-Type':'application/json'},
              body: JSON.stringify({ id_token: response.credential, block }),
            });
            const j = await r.json();
            if (!r.ok) {
              if (j.error === 'not_in_whitelist') {
                onError && onError('Email ' + (j.email || '') + ' не у whitelist. Звернися до vg@sneco.ua');
              } else {
                onError && onError('Помилка авторизації: ' + (j.error || r.status));
              }
              return;
            }
            onSuccess && onSuccess(j);
          } catch (e) {
            onError && onError('Помилка мережі: ' + e.message);
          }
        },
        auto_select: false,
        cancel_on_tap_outside: false,
      });
      window.google.accounts.id.renderButton(container, {
        type: 'standard',
        theme: 'outline',
        size: 'large',
        text: 'continue_with',
        shape: 'pill',
        logo_alignment: 'left',
        width: 320,
        locale: 'uk',
      });
      // One-Tap prompt (мовчки — якщо вже залогінений у Google)
      window.google.accounts.id.prompt();
    } catch (e) {
      onError && onError(e.message);
    }
  }

  window.SnecoAuth = { signInWithGoogle, WORKER };
})();
