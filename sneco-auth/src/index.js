/**
 * snEco Auth Worker
 *
 * Endpoints:
 *   POST /api/otp/request           { email, block }            → { ok }
 *   POST /api/otp/verify            { email, block, code }      → { token }
 *   POST /api/session/verify        { token, block }            → { ok, email, isAdmin, exp }
 *   POST /api/admin/whitelist/get   header: Authorization Bearer
 *                                                                → { blocks: { hr:[…], prices:[…] } }
 *   POST /api/admin/whitelist/update {block, emails[]}          → { ok }
 *
 * Bindings (set via wrangler):
 *   - OTP_KV (KV namespace)
 *   - RESEND_API_KEY (secret)
 *   - JWT_SECRET (secret)
 *   - ADMIN_EMAILS (var, comma-separated, e.g. "vg@sneco.ua,fg@abrisart.com")
 *   - SENDER_EMAIL (var, default "noreply@sneco.ua")
 *   - ALLOWED_ORIGIN (var, default "https://dreamcarua.github.io")
 */

const SUPPORTED_BLOCKS = ['hr', 'prices', 'admin', 'production', 'dashboard', 'inventory-dashboard', 'production-dashboard', 'customer-dashboard', 'finance-dashboard', 'procurement-dashboard'];
// Dashboard-family blocks (всі мають доступ до /api/dashboard/data — той самий D1)
const DASHBOARD_BLOCKS = new Set(['dashboard', 'inventory-dashboard', 'production-dashboard', 'customer-dashboard', 'finance-dashboard', 'procurement-dashboard']);
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;       // 10 MB per file
const MAX_TITLE_LEN = 200;
const MAX_BODY_LEN = 10000;
const MAX_ATTACHMENTS_PER_ITEM = 6;
const OTP_TTL_MS = 10 * 60 * 1000;       // 10 min for OTP itself
const SESSION_TTL_S = 24 * 60 * 60;       // 24 h JWT (was 1h до v2.61)
const ENC = new TextEncoder();
const DEC = new TextDecoder();

function corsHeaders(env) {
  // Allow any origin — endpoints are protected by:
  //   - whitelist (OTP request) — email must be in KV
  //   - JWT (admin endpoints)
  //   - rate limit (CF Workers default)
  // Cookies are not used, so '*' is safe with Authorization header.
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PUT, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    'Access-Control-Max-Age': '60',
  };
}
function jsonResp(body, status, env) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders(env) },
  });
}

function b64url(bytes) {
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function b64urlDecode(str) {
  str = str.replace(/-/g, '+').replace(/_/g, '/');
  while (str.length % 4) str += '=';
  return Uint8Array.from(atob(str), c => c.charCodeAt(0));
}

async function hmacKey(secret) {
  return crypto.subtle.importKey('raw', ENC.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign', 'verify']);
}
async function jwtSign(payload, secret) {
  const header = { alg: 'HS256', typ: 'JWT' };
  const h = b64url(ENC.encode(JSON.stringify(header)));
  const p = b64url(ENC.encode(JSON.stringify(payload)));
  const key = await hmacKey(secret);
  const sig = await crypto.subtle.sign('HMAC', key, ENC.encode(`${h}.${p}`));
  return `${h}.${p}.${b64url(new Uint8Array(sig))}`;
}
async function jwtVerify(token, secret) {
  const [h, p, s] = (token || '').split('.');
  if (!h || !p || !s) throw new Error('malformed');
  const key = await hmacKey(secret);
  const ok = await crypto.subtle.verify('HMAC', key, b64urlDecode(s), ENC.encode(`${h}.${p}`));
  if (!ok) throw new Error('bad signature');
  const payload = JSON.parse(DEC.decode(b64urlDecode(p)));
  if (payload.exp && Math.floor(Date.now() / 1000) > payload.exp) throw new Error('expired');
  return payload;
}

async function sha256Hex(str) {
  const buf = await crypto.subtle.digest('SHA-256', ENC.encode(str));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
}

function normaliseEmail(e) {
  return (e || '').trim().toLowerCase();
}
function generateCode() {
  // 6-digit numeric code
  const arr = new Uint32Array(1);
  crypto.getRandomValues(arr);
  return String(arr[0] % 1000000).padStart(6, '0');
}

function getAdminList(env) {
  return (env.ADMIN_EMAILS || '').split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
}
async function getWhitelist(env, block) {
  // 'admin' block is hardcoded to ADMIN_EMAILS — never editable via KV
  if (block === 'admin') return getAdminList(env);
  const raw = await env.OTP_KV.get(`wl:${block}`);
  if (raw) {
    try { return JSON.parse(raw); } catch (e) {}
  }
  // Default: only admins until edited
  return getAdminList(env);
}
async function setWhitelist(env, block, emails) {
  const cleaned = [...new Set(emails.map(normaliseEmail).filter(Boolean))];
  await env.OTP_KV.put(`wl:${block}`, JSON.stringify(cleaned));
  return cleaned;
}

// === EMAIL TEMPLATE BUILDER ===
// All Resend emails go through this branded shell.
// title = main heading, intro = first paragraph, content = HTML between intro and signature,
// cta = optional { url, label }, footnote = small grey text under content.
function emailTemplate(opts) {
  const brandSite = (opts.env && opts.env.PUBLIC_BASE_URL) || 'https://brand.sneco.ua/';
  const logoUrl = (opts.brandBase || 'https://brand.sneco.ua') + '/logo/snEco-logo-white.png';
  const title = opts.title || 'snEco Brand Bible';
  const intro = opts.intro || '';
  const content = opts.content || '';
  const cta = opts.cta;
  const footnote = opts.footnote || '';
  return `<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f3f3f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1E1E1E">
<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background:#f3f3f0;padding:32px 12px">
  <tr><td align="center">
    <table role="presentation" cellpadding="0" cellspacing="0" width="560" style="max-width:560px;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.05)">
      <!-- HEADER -->
      <tr><td style="background:#1E1E1E;padding:22px 28px;text-align:left">
        <img src="${logoUrl}" alt="snEco" height="28" style="height:28px;display:block;border:0">
      </td></tr>
      <!-- TITLE -->
      <tr><td style="padding:28px 28px 8px">
        <h1 style="margin:0;font-size:20px;font-weight:800;line-height:1.3;color:#1E1E1E;letter-spacing:-0.01em">${title}</h1>
      </td></tr>
      ${intro ? `<tr><td style="padding:0 28px 12px"><p style="margin:0;font-size:14px;line-height:1.6;color:#555">${intro}</p></td></tr>` : ''}
      <!-- CONTENT -->
      <tr><td style="padding:8px 28px 18px">${content}</td></tr>
      ${cta ? `<tr><td style="padding:8px 28px 24px">
        <a href="${cta.url}" style="display:inline-block;background:#FEBF27;color:#1E1E1E;text-decoration:none;font-weight:700;font-size:13px;letter-spacing:0.04em;text-transform:uppercase;padding:11px 22px;border-radius:8px">${cta.label}</a>
      </td></tr>` : ''}
      ${footnote ? `<tr><td style="padding:0 28px 24px"><p style="margin:0;font-size:11.5px;color:#9a9a9a;line-height:1.5">${footnote}</p></td></tr>` : ''}
      <!-- ACCENT BAR -->
      <tr><td style="height:4px;line-height:4px;font-size:0;background:linear-gradient(90deg,#FEBF27 0%,#FEBF27 70%,#96C11F 70%,#96C11F 100%)">&nbsp;</td></tr>
      <!-- FOOTER -->
      <tr><td style="padding:18px 28px;background:#fafafa">
        <p style="margin:0 0 6px;font-size:11px;color:#666;line-height:1.5">
          <strong style="color:#1E1E1E">snEco</strong> · Prime Snack LLC (UA) · Sneco SK s.r.o. (EU)<br>
          <a href="${brandSite}" style="color:#666;text-decoration:underline">brand.sneco.ua</a> ·
          <a href="https://sneco.ua" style="color:#666;text-decoration:underline">sneco.ua</a> ·
          <a href="https://sneco.eu" style="color:#666;text-decoration:underline">sneco.eu</a>
        </p>
        <p style="margin:0;font-size:10.5px;color:#bbb;line-height:1.5">Це автоматичне сповіщення. Не відповідайте на цей лист.</p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>`;
}

async function sendBrandedEmail(env, to, subject, opts) {
  const html = emailTemplate({ ...opts, env });
  const r = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env.RESEND_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      from: env.SENDER_EMAIL || 'noreply@sneco.ua',
      to: Array.isArray(to) ? to : [to],
      subject,
      html,
    }),
  });
  if (!r.ok) {
    const err = await r.text();
    throw new Error(`Resend ${r.status}: ${err.slice(0, 200)}`);
  }
}

async function sendOtpEmail(env, email, code, block) {
  const blockNice = {
    hr: { uk: 'HR', en: 'HR', sk: 'HR' },
    prices: { uk: 'Прайс-листи', en: 'Price lists', sk: 'Cenníky' },
    admin: { uk: 'Розподіл доступу (адмін)', en: 'Access management (admin)', sk: 'Distribúcia prístupu (admin)' },
    production: { uk: 'Виробничі цикли', en: 'Production Cycles', sk: 'Výrobné cykly' },
    dashboard: { uk: 'Sales Analytics', en: 'Sales Analytics', sk: 'Sales Analytics' },
    'inventory-dashboard': { uk: 'Inventory Dashboard', en: 'Inventory Dashboard', sk: 'Inventory Dashboard' },
    'production-dashboard': { uk: 'Production Dashboard', en: 'Production Dashboard', sk: 'Production Dashboard' },
    'customer-dashboard': { uk: 'Customer 360', en: 'Customer 360', sk: 'Customer 360' },
    'finance-dashboard': { uk: 'Finance Dashboard', en: 'Finance Dashboard', sk: 'Finance Dashboard' },
    'procurement-dashboard': { uk: 'Закупки', en: 'Procurement', sk: 'Nákup' },
  }[block] || { uk: block.toUpperCase(), en: block.toUpperCase(), sk: block.toUpperCase() };
  const subject = `Код доступу / Access code / Prístupový kód · ${blockNice.uk} · snEco`;
  const codeBlock = `
    <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="margin:8px 0 18px">
      <tr><td style="background:#FEBF27;border-radius:10px;padding:22px 18px;text-align:center">
        <div style="font-size:11px;font-weight:700;letter-spacing:0.16em;text-transform:uppercase;color:#1E1E1E;opacity:0.7;margin-bottom:8px">Ваш код / Your code / Váš kód</div>
        <div style="font-family:'SF Mono',Menlo,Consolas,monospace;font-size:36px;font-weight:800;letter-spacing:10px;color:#1E1E1E">${code}</div>
      </td></tr>
    </table>
    <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="margin:0 0 4px"><tr>
      <td style="font-size:12px;color:#666;line-height:1.6">
        🇺🇦 ⏱ Код дійсний <strong>10 хв</strong> · Сесія — <strong>1 год</strong>.<br>
        🇬🇧 ⏱ Code valid <strong>10 min</strong> · Session — <strong>1 h</strong>.<br>
        🇸🇰 ⏱ Kód platný <strong>10 min</strong> · Relácia — <strong>1 h</strong>.
      </td>
    </tr></table>`;
  await sendBrandedEmail(env, email, subject, {
    title: `Код доступу · Access code · Prístupový kód`,
    intro: `🇺🇦 Запитано вхід у захищений розділ <strong>${blockNice.uk}</strong>.<br>🇬🇧 Access requested for the protected section <strong>${blockNice.en}</strong>.<br>🇸🇰 Požiadaný prístup do chránenej sekcie <strong>${blockNice.sk}</strong>.`,
    content: codeBlock,
    footnote: '🔒 Якщо ви не запитували — проігноруйте лист. / If you didn\'t request — ignore. / Ak ste nežiadali — ignorujte tento email.',
  });
}

async function readJson(req) {
  try { return await req.json(); } catch (e) { return null; }
}
async function getBearer(req, env) {
  const h = req.headers.get('Authorization') || '';
  const m = h.match(/^Bearer (.+)$/);
  if (!m) return null;
  try { return await jwtVerify(m[1], env.JWT_SECRET); }
  catch (e) { return null; }
}

// === ROUTES ===
async function handleOtpRequest(req, env) {
  const body = await readJson(req);
  if (!body || !body.email || !body.block) return jsonResp({ error: 'email and block required' }, 400, env);
  const email = normaliseEmail(body.email);
  const block = String(body.block).toLowerCase();
  if (!SUPPORTED_BLOCKS.includes(block)) return jsonResp({ error: 'unknown block' }, 400, env);

  const wl = await getWhitelist(env, block);
  if (!wl.includes(email)) {
    // Internal tool — honest mode: explicitly tell the user the email is not in whitelist
    // Small delay to throttle naive enumeration attempts
    await new Promise(r => setTimeout(r, 400 + Math.random() * 300));
    return jsonResp({
      error: 'not_in_whitelist',
      message: 'Цього email немає у whitelist для цього розділу. / This email is not in the whitelist for this section. / Tento email nie je vo whitelist pre túto sekciu.',
      block,
    }, 403, env);
  }

  const code = generateCode();
  const codeHash = await sha256Hex(code);
  await env.OTP_KV.put(`otp:${email}:${block}`, JSON.stringify({
    hash: codeHash,
    exp: Date.now() + OTP_TTL_MS,
  }), { expirationTtl: 700 });

  try {
    await sendOtpEmail(env, email, code, block);
  } catch (e) {
    return jsonResp({ error: 'mail send failed', detail: String(e).slice(0, 200) }, 500, env);
  }
  return jsonResp({ ok: true, message: 'If the address is authorized, a code has been sent.' }, 200, env);
}

async function handleOtpVerify(req, env) {
  const body = await readJson(req);
  if (!body || !body.email || !body.block || !body.code) return jsonResp({ error: 'email, block, code required' }, 400, env);
  const email = normaliseEmail(body.email);
  const block = String(body.block).toLowerCase();
  if (!SUPPORTED_BLOCKS.includes(block)) return jsonResp({ error: 'unknown block' }, 400, env);

  const wl = await getWhitelist(env, block);
  if (!wl.includes(email)) return jsonResp({ error: 'invalid code' }, 401, env);

  const raw = await env.OTP_KV.get(`otp:${email}:${block}`);
  if (!raw) return jsonResp({ error: 'invalid code' }, 401, env);
  let stored; try { stored = JSON.parse(raw); } catch (e) { return jsonResp({ error: 'invalid code' }, 401, env); }
  if (Date.now() > stored.exp) {
    await env.OTP_KV.delete(`otp:${email}:${block}`);
    return jsonResp({ error: 'expired' }, 401, env);
  }
  const codeHash = await sha256Hex(String(body.code).trim());
  if (codeHash !== stored.hash) return jsonResp({ error: 'invalid code' }, 401, env);

  // Success: invalidate code + issue JWT
  await env.OTP_KV.delete(`otp:${email}:${block}`);
  const isAdmin = getAdminList(env).includes(email);
  const now = Math.floor(Date.now() / 1000);
  const token = await jwtSign({
    iss: 'sneco-auth',
    email,
    block,
    isAdmin,
    iat: now,
    exp: now + SESSION_TTL_S,
  }, env.JWT_SECRET);
  return jsonResp({ token, email, isAdmin, exp: now + SESSION_TTL_S }, 200, env);
}

async function handleSessionVerify(req, env) {
  const body = await readJson(req);
  if (!body || !body.token) return jsonResp({ ok: false }, 200, env);
  try {
    const p = await jwtVerify(body.token, env.JWT_SECRET);
    if (body.block && p.block !== body.block) return jsonResp({ ok: false }, 200, env);
    return jsonResp({ ok: true, email: p.email, isAdmin: !!p.isAdmin, exp: p.exp }, 200, env);
  } catch (e) {
    return jsonResp({ ok: false }, 200, env);
  }
}

async function handleAdminGetWhitelist(req, env) {
  const p = await getBearer(req, env);
  if (!p || !p.isAdmin) return jsonResp({ error: 'forbidden' }, 403, env);
  const out = {};
  for (const b of SUPPORTED_BLOCKS) out[b] = await getWhitelist(env, b);
  return jsonResp({ blocks: out, admins: getAdminList(env) }, 200, env);
}
async function handleAdminUpdateWhitelist(req, env) {
  const p = await getBearer(req, env);
  if (!p || !p.isAdmin) return jsonResp({ error: 'forbidden' }, 403, env);
  const body = await readJson(req);
  if (!body || !body.block || !Array.isArray(body.emails)) return jsonResp({ error: 'block and emails[] required' }, 400, env);
  const block = String(body.block).toLowerCase();
  if (!SUPPORTED_BLOCKS.includes(block)) return jsonResp({ error: 'unknown block' }, 400, env);
  const cleaned = await setWhitelist(env, block, body.emails);
  return jsonResp({ ok: true, emails: cleaned }, 200, env);
}

// === IDEAS / TICKETS ===

function uid() {
  // 16-char hex id
  const b = new Uint8Array(8);
  crypto.getRandomValues(b);
  return Array.from(b).map(x => x.toString(16).padStart(2, '0')).join('');
}
function sanitizeStr(s, max) {
  if (typeof s !== 'string') return '';
  return s.trim().slice(0, max);
}
function isValidEmail(e) {
  return typeof e === 'string' && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e);
}
function safeJsonParse(s, fallback) {
  if (!s) return fallback;
  try { return JSON.parse(s); } catch (e) { return fallback; }
}
function validateAttachments(arr) {
  if (!Array.isArray(arr)) return [];
  const out = [];
  for (const a of arr.slice(0, MAX_ATTACHMENTS_PER_ITEM)) {
    if (!a || typeof a !== 'object') continue;
    if (typeof a.key !== 'string' || !/^uploads\/[a-zA-Z0-9_./-]+$/.test(a.key)) continue;
    out.push({
      key: a.key,
      name: sanitizeStr(a.name, 200),
      size: Number(a.size) || 0,
      type: sanitizeStr(a.type, 100),
    });
  }
  return out;
}

async function notifyEmail(env, to, subject, html) {
  if (!env.RESEND_API_KEY) return;
  try {
    await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${env.RESEND_API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        from: env.SENDER_EMAIL || 'noreply@sneco.ua',
        to: Array.isArray(to) ? to : [to],
        subject,
        html,
      }),
    });
  } catch (e) { /* fire-and-forget */ }
}

async function handleIdeasList(req, env) {
  const body = await readJson(req) || {};
  const status = ['open', 'done', 'all'].includes(body.status) ? body.status : 'all';
  let sql = 'SELECT id, title, substr(body, 1, 240) AS preview, author_name, author_email, status, created_at, closed_at, closed_by, attachments, (SELECT COUNT(*) FROM comments WHERE comments.idea_id = ideas.id) AS comment_count FROM ideas';
  const params = [];
  if (status !== 'all') { sql += ' WHERE status = ?'; params.push(status); }
  sql += ' ORDER BY created_at DESC LIMIT 200';
  const { results } = await env.DB.prepare(sql).bind(...params).all();
  // Mask email but keep first letters for personalisation
  const items = (results || []).map(r => ({
    ...r,
    attachments: safeJsonParse(r.attachments, []),
    author_email: maskEmail(r.author_email),
  }));
  return jsonResp({ items }, 200, env);
}
function maskEmail(e) {
  if (!e || typeof e !== 'string') return '';
  const [local, dom] = e.split('@');
  if (!local || !dom) return '';
  return (local.slice(0, 2) + '•••') + '@' + dom;
}

async function handleIdeasGet(req, env) {
  const body = await readJson(req) || {};
  if (!body.id) return jsonResp({ error: 'id required' }, 400, env);
  const idea = await env.DB.prepare('SELECT * FROM ideas WHERE id = ?').bind(body.id).first();
  if (!idea) return jsonResp({ error: 'not found' }, 404, env);
  const { results } = await env.DB.prepare('SELECT id, author_name, author_email, body, attachments, created_at FROM comments WHERE idea_id = ? ORDER BY created_at ASC').bind(body.id).all();
  return jsonResp({
    idea: {
      ...idea,
      author_email: maskEmail(idea.author_email),
      attachments: safeJsonParse(idea.attachments, []),
    },
    comments: (results || []).map(c => ({
      ...c,
      author_email: maskEmail(c.author_email),
      attachments: safeJsonParse(c.attachments, []),
    })),
  }, 200, env);
}

async function handleIdeasCreate(req, env) {
  const body = await readJson(req);
  if (!body) return jsonResp({ error: 'body required' }, 400, env);
  const title = sanitizeStr(body.title, MAX_TITLE_LEN);
  const text = sanitizeStr(body.body, MAX_BODY_LEN);
  const author_name = sanitizeStr(body.author_name, 80);
  const author_email = sanitizeStr(body.author_email, 200).toLowerCase();
  const attachments = validateAttachments(body.attachments);
  if (!title || title.length < 4) return jsonResp({ error: 'title too short' }, 400, env);
  if (!author_name || !isValidEmail(author_email)) return jsonResp({ error: 'name/email required' }, 400, env);

  const id = uid();
  const now = Math.floor(Date.now() / 1000);
  await env.DB.prepare('INSERT INTO ideas (id, title, body, author_email, author_name, status, created_at, attachments) VALUES (?, ?, ?, ?, ?, ?, ?, ?)')
    .bind(id, title, text, author_email, author_name, 'open', now, JSON.stringify(attachments))
    .run();

  // Notify admins
  const admins = getAdminList(env);
  if (admins.length) {
    const link = (env.PUBLIC_BASE_URL || 'https://brand.sneco.ua/') + '#sec-ideas';
    const html = emailTemplate({
      env,
      title: '💡 Нова пропозиція',
      intro: `Від <strong>${escapeHtmlSrv(author_name)}</strong> &lt;${escapeHtmlSrv(author_email)}&gt;`,
      content: `
        <div style="font-size:15px;font-weight:700;color:#1E1E1E;margin:0 0 12px;line-height:1.35">${escapeHtmlSrv(title)}</div>
        <div style="font-size:13px;line-height:1.6;color:#444;background:#f6f6f6;border-left:3px solid #FEBF27;padding:14px 16px;border-radius:4px;white-space:pre-wrap;word-break:break-word">${escapeHtmlSrv(text || '(без опису)')}</div>
        ${attachments.length ? `<div style="font-size:12px;color:#666;margin-top:14px">📎 Прикріплено файлів: <strong>${attachments.length}</strong></div>` : ''}`,
      cta: { url: link, label: 'Переглянути в Brand Bible' },
      footnote: '✓ Як адмін ти можеш позначити пропозицію «зроблено» або повернути в роботу.',
    });
    fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${env.RESEND_API_KEY}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ from: env.SENDER_EMAIL || 'noreply@sneco.ua', to: admins, subject: `💡 Нова пропозиція · ${title}`, html }),
    }).catch(()=>{});
  }
  return jsonResp({ id, ok: true }, 200, env);
}

async function handleIdeasComment(req, env) {
  const body = await readJson(req);
  if (!body) return jsonResp({ error: 'body required' }, 400, env);
  const idea_id = sanitizeStr(body.idea_id, 32);
  const text = sanitizeStr(body.body, MAX_BODY_LEN);
  const author_name = sanitizeStr(body.author_name, 80);
  const author_email = sanitizeStr(body.author_email, 200).toLowerCase();
  const attachments = validateAttachments(body.attachments);
  if (!idea_id) return jsonResp({ error: 'idea_id required' }, 400, env);
  if (!text && attachments.length === 0) return jsonResp({ error: 'body or attachments required' }, 400, env);
  if (!author_name || !isValidEmail(author_email)) return jsonResp({ error: 'name/email required' }, 400, env);

  const idea = await env.DB.prepare('SELECT id, title, author_email FROM ideas WHERE id = ?').bind(idea_id).first();
  if (!idea) return jsonResp({ error: 'idea not found' }, 404, env);

  const id = uid();
  const now = Math.floor(Date.now() / 1000);
  await env.DB.prepare('INSERT INTO comments (id, idea_id, author_email, author_name, body, attachments, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)')
    .bind(id, idea_id, author_email, author_name, text, JSON.stringify(attachments), now)
    .run();

  // Notify admins + idea author (if not the same as commenter)
  const admins = getAdminList(env);
  const recipients = new Set(admins);
  if (idea.author_email && idea.author_email !== author_email) recipients.add(idea.author_email);
  recipients.delete(author_email);
  if (recipients.size) {
    const link = (env.PUBLIC_BASE_URL || 'https://brand.sneco.ua/') + '#sec-ideas';
    const html = emailTemplate({
      env,
      title: '💬 Новий коментар',
      intro: `до пропозиції <strong>${escapeHtmlSrv(idea.title)}</strong>`,
      content: `
        <div style="font-size:12.5px;color:#888;margin:0 0 8px">Від: <strong style="color:#1E1E1E">${escapeHtmlSrv(author_name)}</strong> &lt;${escapeHtmlSrv(author_email)}&gt;</div>
        <div style="font-size:13px;line-height:1.6;color:#444;background:#f6f6f6;border-left:3px solid #96C11F;padding:14px 16px;border-radius:4px;white-space:pre-wrap;word-break:break-word">${escapeHtmlSrv(text || '(без тексту)')}</div>
        ${attachments.length ? `<div style="font-size:12px;color:#666;margin-top:14px">📎 Прикріплено файлів: <strong>${attachments.length}</strong></div>` : ''}`,
      cta: { url: link, label: 'Відкрити пропозицію' },
    });
    fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${env.RESEND_API_KEY}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ from: env.SENDER_EMAIL || 'noreply@sneco.ua', to: [...recipients], subject: `💬 Коментар · ${idea.title}`, html }),
    }).catch(()=>{});
  }
  return jsonResp({ id, ok: true }, 200, env);
}

async function handleIdeasStatus(req, env, newStatus) {
  const p = await getBearer(req, env);
  if (!p || !p.isAdmin) return jsonResp({ error: 'forbidden' }, 403, env);
  const body = await readJson(req);
  if (!body || !body.idea_id) return jsonResp({ error: 'idea_id required' }, 400, env);
  const now = Math.floor(Date.now() / 1000);
  const closed_at = newStatus === 'done' ? now : null;
  const closed_by = newStatus === 'done' ? p.email : null;
  await env.DB.prepare('UPDATE ideas SET status = ?, closed_at = ?, closed_by = ? WHERE id = ?')
    .bind(newStatus, closed_at, closed_by, body.idea_id).run();
  return jsonResp({ ok: true }, 200, env);
}

async function handleIdeasUpload(req, env) {
  if (!env.FILES_BUCKET) return jsonResp({ error: 'R2 not configured' }, 500, env);
  const url = new URL(req.url);
  const filename = sanitizeStr(url.searchParams.get('filename') || 'file', 100);
  const contentType = req.headers.get('Content-Type') || 'application/octet-stream';
  const cl = Number(req.headers.get('Content-Length') || 0);
  if (cl > MAX_UPLOAD_BYTES) return jsonResp({ error: 'file too large (max 10 MB)' }, 413, env);

  // Generate safe key: uploads/YYYYMM/<random>-<sanitized-filename>
  const now = new Date();
  const month = `${now.getUTCFullYear()}${String(now.getUTCMonth() + 1).padStart(2, '0')}`;
  const safe = filename.replace(/[^a-zA-Z0-9_.-]/g, '_').slice(0, 80);
  const key = `uploads/${month}/${uid()}-${safe}`;

  const data = await req.arrayBuffer();
  if (data.byteLength > MAX_UPLOAD_BYTES) return jsonResp({ error: 'file too large (max 10 MB)' }, 413, env);

  await env.FILES_BUCKET.put(key, data, {
    httpMetadata: { contentType },
  });
  // Public access: served via Worker /files/<key> route
  return jsonResp({ key, size: data.byteLength, type: contentType, name: filename }, 200, env);
}

async function handleFileServe(req, env, path) {
  if (!env.FILES_BUCKET) return new Response('not found', { status: 404, headers: corsHeaders(env) });
  const key = path.replace(/^\/files\//, '');
  if (!/^uploads\/[a-zA-Z0-9_./-]+$/.test(key)) return new Response('not found', { status: 404, headers: corsHeaders(env) });
  const obj = await env.FILES_BUCKET.get(key);
  if (!obj) return new Response('not found', { status: 404, headers: corsHeaders(env) });
  const headers = new Headers(corsHeaders(env));
  obj.writeHttpMetadata(headers);
  headers.set('Cache-Control', 'public, max-age=86400');
  return new Response(obj.body, { headers });
}

function escapeHtmlSrv(s) {
  return String(s || '').replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' })[c]);
}

// =====================================================================
// DASHBOARD endpoints (added v2.50)
// =====================================================================
//
// /api/dashboard/ingest    — auth via X-Sync-Key header (matches env.SYNC_API_KEY)
//                            Body: { entity: 'demands'|..., rows: [{...}], started_at, finished_at? }
//                            Upserts batch into ms_<entity> table.
// /api/dashboard/last-sync — public, no auth. Returns last 5 sync_log rows.
// /api/dashboard/data      — JWT-protected (block='dashboard').
//                            Body: { type: 'demands'|'payments'|...|'summary', from?, to?, limit? }
//
// SECURITY:
//  • SYNC_API_KEY is a Worker secret (wrangler secret put SYNC_API_KEY)
//  • Set in GitHub Actions repo Secrets too — used to call /api/dashboard/ingest
//  • Without it ingest returns 401
//
// Schema:    schema-dashboard.sql (apply via wrangler d1 execute)
// =====================================================================

// Maps entity name → table + allowed columns (whitelist for safety)
// v2.78 (multi-currency, 2026-05-20): + currency, rate_to_uah, sum_orig_kop у транзакційних
// таблицях. sum_kop тепер ЗАВЖДИ у UAH (нормалізовано через rate_to_uah), sum_orig_kop —
// оригінал у валюті документа (EUR-сценах для EUR-doc, UAH-копійках для UAH-doc).
const DASHBOARD_TABLES = {
  demands: {
    table: 'ms_demands',
    cols: ['id','ms_moment','name','sum_kop','organization','agent','agent_id','store','contract','state','applicable','vat_included','vat_enabled','payed_sum_kop','currency','rate_to_uah','sum_orig_kop','raw_json','ingested_at'],
  },
  payments: {
    table: 'ms_payments',
    cols: ['id','ms_moment','payment_type','name','sum_kop','organization','agent','agent_id','account','expense_item','expense_item_id','payment_purpose','currency','rate_to_uah','sum_orig_kop','raw_json','ingested_at'],
  },
  orders: {
    table: 'ms_orders',
    cols: ['id','ms_moment','name','sum_kop','shipped_sum_kop','payed_sum_kop','organization','agent','agent_id','store','contract','state','delivery_planned_moment','currency','rate_to_uah','sum_orig_kop','raw_json','ingested_at'],
  },
  returns: {
    table: 'ms_returns',
    cols: ['id','ms_moment','name','sum_kop','organization','agent','agent_id','store','demand_id','currency','rate_to_uah','sum_orig_kop','raw_json','ingested_at'],
  },
  products: {
    table: 'ms_products',
    cols: ['id','name','code','external_code','article','uom','weight_g','volume_ml','sale_price_kop','buy_price_kop','min_price_kop','product_folder','archived','ean_codes','raw_json','ingested_at'],
  },
  counterparties: {
    table: 'ms_counterparties',
    cols: ['id','name','full_name','code','external_code','inn','edrpou','legal_address','legal_address_comment','actual_address','email','phone','fax','tags','company_type','balance_kop','overdue_debt_kop','state','description','archived','raw_json','ingested_at'],
  },
  invoices_out: {
    table: 'ms_invoices_out',
    cols: ['id','ms_moment','name','sum_kop','organization','agent','agent_id','payment_planned_moment','payed_sum_kop','state','currency','rate_to_uah','sum_orig_kop','raw_json','ingested_at'],
  },
  moves: {
    table: 'ms_moves',
    cols: ['id','ms_moment','name','source_store','target_store','organization','raw_json','ingested_at'],
  },
  processing_plans: {
    table: 'ms_processing_plans',
    cols: ['id','name','code','parent_product','archived','raw_json','ingested_at'],
  },
  // v2.70: товарні позиції з відвантажень. Composite primary key (demand_id, position_idx).
  // Customer 360 використовує для TOP-10 продуктів per клієнт.
  demand_positions: {
    table: 'ms_demand_positions',
    cols: ['demand_id','position_idx','product_name','product_id','quantity','price_kop','sum_kop','discount_pct','agent_id','agent','ms_moment','currency','rate_to_uah','sum_orig_kop','price_orig_kop','raw_json','ingested_at'],
  },
  // v2.77.5 — Procurement Dashboard (Pylyp PR #1): 4 нові entities для виробничого циклу
  processings: {
    table: 'ms_processings',
    cols: ['id','ms_moment','name','organization_id','organization','processing_plan_id','processing_plan_name','quantity','processing_sum_kop','applicable','currency','rate_to_uah','processing_sum_orig_kop','raw_json','updated_at'],
  },
  processing_materials: {
    table: 'ms_processing_materials',
    cols: ['id','processing_id','position_id','assortment_id','quantity','price_kop','currency','rate_to_uah','price_orig_kop','raw_json'],
  },
  processing_products: {
    table: 'ms_processing_products',
    cols: ['id','processing_id','position_id','assortment_id','quantity','price_kop','currency','rate_to_uah','price_orig_kop','raw_json'],
  },
  stocks: {
    table: 'ms_stocks',
    cols: ['assortment_id','name','code','article','folder_name','folder_path','uom_name','stock','in_transit','reserve','quantity','price_kop','sale_price_kop','stock_days','snapshot_at','currency','rate_to_uah','price_orig_kop','sale_price_orig_kop','raw_json'],
  },
};

const INGEST_BATCH_LIMIT = 500;          // max rows per single POST
const INGEST_TOTAL_LIMIT = 50000;        // hard ceiling per request

async function handleDashboardIngest(req, env) {
  // Auth
  const key = req.headers.get('X-Sync-Key') || '';
  if (!env.SYNC_API_KEY || key !== env.SYNC_API_KEY) {
    return jsonResp({ error: 'unauthorized' }, 401, env);
  }
  const body = await readJson(req);
  if (!body) return jsonResp({ error: 'body required' }, 400, env);

  // Sync log mode: caller can POST { sync_log: { ... } } to write a sync_log row
  if (body.sync_log) {
    const log = body.sync_log;
    const startedAt = Number(log.started_at) || Math.floor(Date.now() / 1000);
    await env.DB.prepare(
      `INSERT INTO ms_sync_log (started_at, finished_at, status, trigger, entities, errors, duration_ms, data_window_from, data_window_to)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).bind(
      startedAt,
      log.finished_at != null ? Number(log.finished_at) : null,
      String(log.status || 'success'),
      String(log.trigger || 'cron'),
      log.entities ? JSON.stringify(log.entities) : null,
      log.errors ? JSON.stringify(log.errors) : null,
      log.duration_ms != null ? Number(log.duration_ms) : null,
      log.data_window_from || null,
      log.data_window_to || null,
    ).run();
    return jsonResp({ ok: true, mode: 'sync_log' }, 200, env);
  }

  // Entity batch mode: body = { entity, rows: [...] }
  const entity = String(body.entity || '').toLowerCase();
  const def = DASHBOARD_TABLES[entity];
  if (!def) return jsonResp({ error: 'unknown entity', supported: Object.keys(DASHBOARD_TABLES) }, 400, env);

  const rows = Array.isArray(body.rows) ? body.rows : [];
  if (rows.length === 0) return jsonResp({ ok: true, inserted: 0 }, 200, env);
  if (rows.length > INGEST_TOTAL_LIMIT) return jsonResp({ error: 'too many rows', limit: INGEST_TOTAL_LIMIT }, 400, env);

  // Build INSERT OR REPLACE
  const placeholders = '(' + def.cols.map(() => '?').join(',') + ')';
  const sql = `INSERT OR REPLACE INTO ${def.table} (${def.cols.join(',')}) VALUES ${placeholders}`;
  const ingestedAt = Math.floor(Date.now() / 1000);

  let inserted = 0;
  // Split into batches of INGEST_BATCH_LIMIT
  for (let i = 0; i < rows.length; i += INGEST_BATCH_LIMIT) {
    const batch = rows.slice(i, i + INGEST_BATCH_LIMIT);
    const stmts = batch.map(row => {
      const vals = def.cols.map(c => {
        if (c === 'ingested_at') return ingestedAt;
        const v = row[c];
        if (v === undefined) return null;
        if (typeof v === 'object' && v !== null) return JSON.stringify(v);
        if (typeof v === 'boolean') return v ? 1 : 0;
        return v;
      });
      return env.DB.prepare(sql).bind(...vals);
    });
    await env.DB.batch(stmts);
    inserted += batch.length;
  }

  return jsonResp({ ok: true, entity, inserted, table: def.table }, 200, env);
}

async function handleDashboardLastSync(req, env) {
  const { results } = await env.DB.prepare(
    `SELECT id, started_at, finished_at, status, trigger, entities, errors, duration_ms, data_window_from, data_window_to
     FROM ms_sync_log ORDER BY started_at DESC LIMIT 5`
  ).all();
  const items = (results || []).map(r => ({
    ...r,
    entities: safeJsonParse(r.entities, null),
    errors: safeJsonParse(r.errors, null),
  }));
  return jsonResp({ items }, 200, env);
}

async function handleDashboardData(req, env) {
  // Auth: JWT block='dashboard' OR X-Sync-Key (для scheduled tasks типу daily_briefing)
  // v2.73.0 Phase B-2: SYNC_API_KEY дає read-access без expiration (alternative до 24h JWT).
  const syncKey = req.headers.get('X-Sync-Key') || '';
  if (!syncKey || syncKey !== env.SYNC_API_KEY) {
    // Не sync-key — перевіряємо JWT
    const auth = req.headers.get('Authorization') || '';
    const token = auth.startsWith('Bearer ') ? auth.slice(7) : '';
    if (!token) return jsonResp({ error: 'unauthorized' }, 401, env);
    let payload;
    try { payload = await jwtVerify(token, env.JWT_SECRET); }
    catch (e) { return jsonResp({ error: 'invalid token' }, 401, env); }
    if (!DASHBOARD_BLOCKS.has(payload.block) && !payload.isAdmin) {
      return jsonResp({ error: 'forbidden' }, 403, env);
    }
  }

  const body = await readJson(req) || {};
  const type = String(body.type || '').toLowerCase();
  const def = DASHBOARD_TABLES[type];

  // Special: 'summary' returns counts of all tables
  if (type === 'summary') {
    const queries = Object.values(DASHBOARD_TABLES).map(d => env.DB.prepare(`SELECT COUNT(*) AS n FROM ${d.table}`));
    const results = await env.DB.batch(queries);
    const summary = {};
    Object.keys(DASHBOARD_TABLES).forEach((k, i) => { summary[k] = results[i].results[0].n; });
    return jsonResp({ summary }, 200, env);
  }

  if (!def) return jsonResp({ error: 'unknown type', supported: [...Object.keys(DASHBOARD_TABLES), 'summary'] }, 400, env);

  // Filters
  // v2.72.1: cap bumped 10000 → 100000 — Customer 360 + Finance потребують
  // повний історичний dataset (22k demands + 24k payments + ще буде demand_positions ~100k+).
  // CF Workers heap = 128MB → JSON ~100K rows × 500 bytes = ~50MB, влізає.
  const limit  = Math.min(Math.max(Number(body.limit) || 1000, 1), 100000);
  const offset = Math.max(Number(body.offset) || 0, 0);
  const from   = body.from ? String(body.from) : null;
  const to     = body.to   ? String(body.to)   : null;

  // v2.75.4 HOTFIX: НЕ повертаємо raw_json — це масивна JSON колонка яка
  // переповнює CF Worker heap (128MB) на великих таблицях (ms_demand_positions
  // ~50K+ rows × ~2KB raw_json = >200MB response → Worker 503).
  // v2.76.0: гібрид — викидаємо raw_json ТІЛЬКИ для масивних таблиць.
  // Для payments / demands / orders / returns / invoices_out — повертаємо raw_json:
  //   ~32K × ~500 байт = 16MB, безпечно. Це критично для getExpenseItem fallback
  //   у Finance dashboard (коли expense_item колонка ще порожня до next full sync).
  const HEAVY_TABLES = ['demand_positions', 'products', 'counterparties'];
  const skipRawJson = HEAVY_TABLES.includes(type);
  const cols = skipRawJson ? def.cols.filter(c => c !== 'raw_json') : def.cols;
  let sql = `SELECT ${cols.join(', ')} FROM ${def.table}`;
  const params = [];
  const where = [];
  if (def.cols.includes('ms_moment')) {
    if (from) { where.push('ms_moment >= ?'); params.push(from); }
    if (to)   { where.push('ms_moment <= ?'); params.push(to); }
  }
  if (where.length) sql += ' WHERE ' + where.join(' AND ');
  if (def.cols.includes('ms_moment')) sql += ' ORDER BY ms_moment DESC';
  sql += ' LIMIT ? OFFSET ?';
  params.push(limit, offset);

  const { results } = await env.DB.prepare(sql).bind(...params).all();
  return jsonResp({ items: results || [], limit, offset, count: (results || []).length }, 200, env);
}

// =====================================================================
// v2.75.0 — CRM-LOG endpoints (D1 backend + MoySklad write-back)
// =====================================================================

// Auth helper — повертає payload з JWT (для author tracking)
async function _crmAuth(req, env) {
  const auth = req.headers.get('Authorization') || '';
  const token = auth.startsWith('Bearer ') ? auth.slice(7) : '';
  if (!token) return null;
  try {
    const payload = await jwtVerify(token, env.JWT_SECRET);
    if (!DASHBOARD_BLOCKS.has(payload.block) && !payload.isAdmin) return null;
    return payload;
  } catch (e) { return null; }
}

// GET notes for customer
async function handleCrmNotesList(req, env) {
  const auth = await _crmAuth(req, env);
  if (!auth) return jsonResp({ error: 'unauthorized' }, 401, env);
  const body = await readJson(req) || {};
  const customerKey = String(body.customer_key || '').trim();
  if (!customerKey) return jsonResp({ error: 'customer_key required' }, 400, env);
  const { results } = await env.DB.prepare(
    `SELECT id, note_date, note_type, summary, next_step, next_date, author_email, author_name, created_at, ms_synced
     FROM customer_notes WHERE customer_key = ? AND deleted = 0
     ORDER BY note_date DESC, created_at DESC LIMIT 200`
  ).bind(customerKey).all();
  return jsonResp({ items: results || [] }, 200, env);
}

// CREATE note — also push to MoySklad counterparty.description
async function handleCrmNoteCreate(req, env) {
  const auth = await _crmAuth(req, env);
  if (!auth) return jsonResp({ error: 'unauthorized' }, 401, env);
  const body = await readJson(req) || {};
  const customerKey = String(body.customer_key || '').trim();
  const customerId = String(body.customer_id || '').trim() || null;  // MoySklad cp.id для PATCH
  const customerName = String(body.customer_name || '').trim();
  const noteDate = String(body.note_date || '').trim();
  const noteType = String(body.note_type || '').trim();
  const summary = String(body.summary || '').trim();
  const nextStep = String(body.next_step || '').trim() || null;
  const nextDate = String(body.next_date || '').trim() || null;

  if (!customerKey || !customerName || !noteDate || !noteType || !summary) {
    return jsonResp({ error: 'customer_key, customer_name, note_date, note_type, summary обовʼязкові' }, 400, env);
  }

  const id = uid();
  const now = Math.floor(Date.now() / 1000);
  await env.DB.prepare(
    `INSERT INTO customer_notes
     (id, customer_key, customer_id, customer_name, note_date, note_type, summary, next_step, next_date,
      author_email, author_name, created_at, ms_synced)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)`
  ).bind(
    id, customerKey, customerId, customerName, noteDate, noteType, summary, nextStep, nextDate,
    auth.email, auth.email.split('@')[0], now
  ).run();

  // MoySklad write-back (fire-and-forget — не блокуємо response)
  // Якщо нема customerId (віртуальний клієнт) — skip MS sync
  if (customerId && env.MOYSKLAD_TOKEN) {
    const noteText = `[${noteDate} · ${auth.email} · ${noteType}] ${summary}`
      + (nextStep ? `\nНаступний крок: ${nextStep}` : '')
      + (nextDate ? `\nНаступний контакт: ${nextDate}` : '');
    // Async fire-and-forget through ctx.waitUntil якщо доступний
    (async () => {
      try {
        // 1. GET existing counterparty description
        const cur = await fetch(
          `https://api.moysklad.ru/api/remap/1.2/entity/counterparty/${customerId}`,
          { headers: { Authorization: `Bearer ${env.MOYSKLAD_TOKEN}` } }
        );
        if (!cur.ok) throw new Error(`MS GET ${cur.status}`);
        const cp = await cur.json();
        const existingDesc = (cp.description || '').trim();
        // 2. Prepend new note (newest first), keep existing below separator
        const newDesc = `${noteText}\n\n--- CRM-лог (попередні нотатки) ---\n${existingDesc}`.slice(0, 4096); // MS limit
        // 3. PATCH counterparty
        const patch = await fetch(
          `https://api.moysklad.ru/api/remap/1.2/entity/counterparty/${customerId}`,
          {
            method: 'PUT',
            headers: { Authorization: `Bearer ${env.MOYSKLAD_TOKEN}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ description: newDesc })
          }
        );
        if (!patch.ok) throw new Error(`MS PUT ${patch.status}: ${(await patch.text()).slice(0,200)}`);
        // 4. Mark synced у D1
        await env.DB.prepare(
          `UPDATE customer_notes SET ms_synced = 1, ms_sync_at = ?, ms_sync_error = NULL WHERE id = ?`
        ).bind(Math.floor(Date.now()/1000), id).run();
      } catch (e) {
        // Log error у D1 — manager бачить ⚠ у UI
        try {
          await env.DB.prepare(
            `UPDATE customer_notes SET ms_sync_error = ? WHERE id = ?`
          ).bind(String(e).slice(0, 300), id).run();
        } catch (_) {}
      }
    })();
  }

  return jsonResp({ ok: true, id, ms_sync_pending: !!customerId }, 200, env);
}

// UPDATE existing note (edit form)
async function handleCrmNoteUpdate(req, env) {
  const auth = await _crmAuth(req, env);
  if (!auth) return jsonResp({ error: 'unauthorized' }, 401, env);
  const body = await readJson(req) || {};
  const id = String(body.id || '').trim();
  if (!id) return jsonResp({ error: 'id required' }, 400, env);
  const now = Math.floor(Date.now() / 1000);
  await env.DB.prepare(
    `UPDATE customer_notes SET
       note_date = COALESCE(?, note_date),
       note_type = COALESCE(?, note_type),
       summary   = COALESCE(?, summary),
       next_step = ?, next_date = ?,
       updated_at = ?
     WHERE id = ?`
  ).bind(
    body.note_date || null, body.note_type || null, body.summary || null,
    body.next_step ?? null, body.next_date ?? null, now, id
  ).run();
  return jsonResp({ ok: true }, 200, env);
}

// DELETE — soft delete (deleted = 1)
async function handleCrmNoteDelete(req, env) {
  const auth = await _crmAuth(req, env);
  if (!auth) return jsonResp({ error: 'unauthorized' }, 401, env);
  const body = await readJson(req) || {};
  const id = String(body.id || '').trim();
  if (!id) return jsonResp({ error: 'id required' }, 400, env);
  await env.DB.prepare(`UPDATE customer_notes SET deleted = 1 WHERE id = ?`).bind(id).run();
  return jsonResp({ ok: true }, 200, env);
}

// === ENTRY ===
export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(env) });
    }
    const url = new URL(request.url);

    // Public file serve via /files/uploads/...
    if (request.method === 'GET' && url.pathname.startsWith('/files/')) {
      return await handleFileServe(request, env, url.pathname);
    }
    // Upload: PUT for raw body
    if (request.method === 'PUT' && url.pathname === '/api/ideas/upload') {
      return await handleIdeasUpload(request, env);
    }
    if (request.method !== 'POST') {
      return jsonResp({ error: 'method not allowed' }, 405, env);
    }
    try {
      switch (url.pathname) {
        case '/api/otp/request':            return await handleOtpRequest(request, env);
        case '/api/otp/verify':             return await handleOtpVerify(request, env);
        case '/api/session/verify':         return await handleSessionVerify(request, env);
        case '/api/admin/whitelist/get':    return await handleAdminGetWhitelist(request, env);
        case '/api/admin/whitelist/update': return await handleAdminUpdateWhitelist(request, env);
        case '/api/ideas/list':             return await handleIdeasList(request, env);
        case '/api/ideas/get':              return await handleIdeasGet(request, env);
        case '/api/ideas/create':           return await handleIdeasCreate(request, env);
        case '/api/ideas/comment':          return await handleIdeasComment(request, env);
        case '/api/ideas/close':            return await handleIdeasStatus(request, env, 'done');
        case '/api/ideas/reopen':           return await handleIdeasStatus(request, env, 'open');
        // Dashboard (added v2.50)
        case '/api/dashboard/ingest':       return await handleDashboardIngest(request, env);
        case '/api/dashboard/last-sync':    return await handleDashboardLastSync(request, env);
        case '/api/dashboard/data':         return await handleDashboardData(request, env);
        // CRM notes (v2.75.0) — D1 backend + MoySklad write-back
        case '/api/crm-notes/list':         return await handleCrmNotesList(request, env);
        case '/api/crm-notes/create':       return await handleCrmNoteCreate(request, env);
        case '/api/crm-notes/update':       return await handleCrmNoteUpdate(request, env);
        case '/api/crm-notes/delete':       return await handleCrmNoteDelete(request, env);
        default: return jsonResp({ error: 'not found' }, 404, env);
      }
    } catch (e) {
      return jsonResp({ error: 'internal', detail: String(e).slice(0, 200) }, 500, env);
    }
  },
};
