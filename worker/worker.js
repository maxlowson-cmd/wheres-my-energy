/* Where's My Energy From? relay: contact form to Telegram, anonymous postcode district counts, and the half-hourly rebuild trigger.
   Secrets, set in Cloudflare and never in this file: TELEGRAM_TOKEN, TELEGRAM_CHAT, STATS_KEY, GITHUB_TOKEN (optional).
   Binding: DB (D1 database, see schema.sql). */

const DISTRICT = /^[A-Z]{1,2}\d[A-Z\d]?$/;
const CONTACT_LIMIT = 5; // messages per person per hour

const allowed = (env) => (env.ALLOWED_ORIGINS || '').split(',').map((s) => s.trim()).filter(Boolean);

function cors(request, env) {
  const origin = request.headers.get('Origin') || '';
  if (!allowed(env).includes(origin)) return null;
  return { 'Access-Control-Allow-Origin': origin, 'Access-Control-Allow-Methods': 'POST, OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type', 'Access-Control-Max-Age': '86400', Vary: 'Origin' };
}

const reply = (status, headers, body) => new Response(body == null ? null : JSON.stringify(body), { status, headers: { ...headers, ...(body == null ? {} : { 'Content-Type': 'application/json' }) } });
const today = () => new Date().toISOString().slice(0, 10);

async function telegram(env, text) {
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_TOKEN}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: env.TELEGRAM_CHAT, text: text.slice(0, 4000), disable_web_page_preview: true }),
  });
  return r.ok;
}

async function sha(text) {
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, '0')).join('').slice(0, 32);
}

/* counts a hit against a named limit and says whether it is still allowed; the salted hash means no IP address is stored */
async function underLimit(env, key, windowMs, max) {
  const slot = Math.floor(Date.now() / windowMs);
  const row = await env.DB.prepare('INSERT INTO limits (key, slot, n) VALUES (?1, ?2, 1) ON CONFLICT (key, slot) DO UPDATE SET n = n + 1 RETURNING n').bind(key, slot).first();
  return row.n <= max;
}

async function readJson(request) {
  const text = await request.text();
  if (text.length > 6000) return null;
  try { const v = JSON.parse(text); return v && typeof v === 'object' ? v : null; } catch (e) { return null; }
}

async function count(request, env, headers) {
  const body = await readJson(request);
  const d = body && typeof body.d === 'string' ? body.d.toUpperCase() : '';
  if (!DISTRICT.test(d)) return reply(400, headers, { error: 'bad district' });
  await env.DB.prepare('INSERT INTO counts (day, district, n) VALUES (?1, ?2, 1) ON CONFLICT (day, district) DO UPDATE SET n = n + 1').bind(today(), d).run();
  return reply(204, headers);
}

async function contact(request, env, headers) {
  const body = await readJson(request);
  if (!body) return reply(400, headers, { error: 'bad request' });
  if (body.website) return reply(204, headers); // the hidden field only a bot fills in: look successful, send nothing
  const message = String(body.message || '').trim();
  const from = String(body.reply || '').trim().slice(0, 200);
  if (message.length < 3 || message.length > 2000) return reply(400, headers, { error: 'length' });
  const who = await sha(`${request.headers.get('CF-Connecting-IP') || ''}|${env.STATS_KEY}`);
  if (!await underLimit(env, `contact:${who}`, 3600000, CONTACT_LIMIT)) return reply(429, headers, { error: 'too many' });
  const ok = await telegram(env, `New message from the site\n\n${message}${from ? `\n\nReply to: ${from}` : ''}`);
  return ok ? reply(204, headers) : reply(502, headers, { error: 'not delivered' });
}

async function stats(url, env) {
  if (!env.STATS_KEY || url.searchParams.get('key') !== env.STATS_KEY) return new Response('Not found', { status: 404 });
  const days = Math.min(365, Math.max(1, Number(url.searchParams.get('days')) || 30));
  const since = new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
  const { results } = await env.DB.prepare('SELECT district, SUM(n) AS n FROM counts WHERE day >= ?1 GROUP BY district ORDER BY n DESC').bind(since).all();
  return new Response(JSON.stringify({ since, total: results.reduce((a, r) => a + r.n, 0), districts: results }), { headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } });
}

/* tell GitHub to rebuild; its own schedule has been unreliable. Does nothing until GITHUB_TOKEN is set. */
async function rebuild(env) {
  if (!env.GITHUB_TOKEN || !env.GH_REPO) return;
  const r = await fetch(`https://api.github.com/repos/${env.GH_REPO}/actions/workflows/${env.GH_WORKFLOW || 'build.yml'}/dispatches`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${env.GITHUB_TOKEN}`, Accept: 'application/vnd.github+json', 'User-Agent': 'wheres-my-energy-relay', 'Content-Type': 'application/json' },
    body: JSON.stringify({ ref: env.GH_REF || 'main' }),
  });
  if (!r.ok && await underLimit(env, 'rebuild-alert', 6 * 3600000, 1)) await telegram(env, `The site rebuild could not be started (GitHub said ${r.status}).`);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === 'GET' && url.pathname === '/stats') return stats(url, env);
    const headers = cors(request, env);
    if (!headers) return new Response('Not found', { status: 404 });
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers });
    if (request.method === 'POST' && url.pathname === '/count') return count(request, env, headers);
    if (request.method === 'POST' && url.pathname === '/contact') return contact(request, env, headers);
    return reply(404, headers, { error: 'not found' });
  },
  async scheduled(event, env, ctx) {
    ctx.waitUntil(rebuild(env));
  },
};
