/* Where's My Energy From? relay: contact form to Telegram, anonymous postcode district counts, morning email alerts, and the half-hourly rebuild trigger.
   Secrets, set in Cloudflare and never in this file: TELEGRAM_TOKEN, TELEGRAM_CHAT, STATS_KEY, RESEND_KEY (optional), GITHUB_TOKEN (optional).
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

/* email alerts: one message each morning. Nothing is sent until the address owner confirms, and every email can unsubscribe, which deletes the row. */
const EMAIL = /^[^\s@]{1,64}@[^\s@]+\.[^\s@]{2,}$/;
const SITE_URL = 'https://wheresmyenergyfrom.co.uk';
const RELAY_URL = 'https://wheres-my-energy-relay.wheresmyenergy.workers.dev';
const ALERT_CRON = '30 6,7 * * *'; // Cloudflare's clock is UTC, so this covers 07:30 UK time in winter and summer
const DAILY_CAP = 95; // stays inside the email service's free daily limit, leaving room for confirmation emails
const SLOT = 1800000, LONDON = 'Europe/London';
const part = (options) => new Intl.DateTimeFormat('en-GB', { timeZone: LONDON, ...options });
const ukHour = part({ hour: 'numeric', hourCycle: 'h23' }), ukClock = part({ hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }), ukDay = part({ year: 'numeric', month: '2-digit', day: '2-digit' });

const stopLink = (token) => `${RELAY_URL}/alerts/stop?t=${token}`;

/* emails use tables and inline styles because mail apps ignore most modern CSS; no images, as many apps block them */
const FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif";
const escapeHtml = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const capital = (s) => s[0].toUpperCase() + s.slice(1);
const emailButton = (href, label) => `<a href="${href}" style="display:inline-block;background:#06704b;color:#f2fbf7;font-family:${FONT};font-size:17px;font-weight:700;line-height:1;text-decoration:none;padding:17px 28px;border-radius:999px">${label}</a>`;
function emailShell(preview, inner, foot) {
  return `<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light"></head><body style="margin:0;padding:0;background:#dfeae6"><div style="display:none;max-height:0;overflow:hidden">${preview}</div><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#dfeae6"><tr><td align="center" style="padding:28px 14px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px"><tr><td style="padding:0 6px 16px;font-family:${FONT};font-size:15px;font-weight:700;color:#06704b">Where's my energy from?</td></tr><tr><td style="background:#ffffff;border-radius:18px;padding:30px 26px;font-family:${FONT};color:#10302a">${inner}</td></tr><tr><td style="padding:18px 6px 0;font-family:${FONT};font-size:13px;line-height:1.5;color:#4c6a62">${foot}</td></tr></table></td></tr></table></body></html>`;
}

async function sendEmails(env, mails) {
  const r = await fetch('https://api.resend.com/emails/batch', {
    method: 'POST',
    headers: { Authorization: `Bearer ${env.RESEND_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(mails.map((m) => ({ from: env.ALERT_FROM || "Where's My Energy From? <alerts@mail.wheresmyenergyfrom.co.uk>", ...m }))),
  });
  return r.ok;
}

async function regionOf(district) {
  const r = await fetch(`https://api.carbonintensity.org.uk/regional/postcode/${district}`, { headers: { Accept: 'application/json' } });
  if (!r.ok) return null;
  const row = (await r.json()).data[0];
  return row ? row.regionid : null;
}

async function alertSignup(request, env, headers) {
  if (!env.RESEND_KEY) return reply(503, headers, { error: 'not set up' });
  const body = await readJson(request);
  if (!body) return reply(400, headers, { error: 'bad request' });
  if (body.website) return reply(204, headers);
  const email = String(body.email || '').trim().toLowerCase();
  const district = String(body.d || '').toUpperCase();
  if (email.length > 200 || !EMAIL.test(email) || !DISTRICT.test(district)) return reply(400, headers, { error: 'bad details' });
  const who = await sha(`${request.headers.get('CF-Connecting-IP') || ''}|${env.STATS_KEY}`);
  if (!await underLimit(env, `alerts:${who}`, 3600000, 5)) return reply(429, headers, { error: 'too many' });
  if (!await underLimit(env, `alerts-to:${await sha(`${email}|${env.STATS_KEY}`)}`, 86400000, 2)) return reply(204, headers); // nobody can use the form to flood someone's inbox
  const region = await regionOf(district);
  if (!region) return reply(400, headers, { error: 'unknown district' });
  const row = await env.DB.prepare('INSERT INTO subscribers (email, token, district, region, confirmed, created) VALUES (?1, ?2, ?3, ?4, 0, ?5) ON CONFLICT (email) DO UPDATE SET district = ?3, region = ?4 RETURNING token, confirmed')
    .bind(email, crypto.randomUUID().replaceAll('-', ''), district, region, Date.now()).first();
  if (row.confirmed) return reply(204, headers);
  const confirm = `${RELAY_URL}/alerts/confirm?t=${row.token}`;
  const ok = await sendEmails(env, [{
    to: [email], subject: 'Confirm your morning energy email',
    text: `Confirm to get one email each morning with the cleanest time to use electricity around ${district}:\n\n${confirm}\n\nDidn't ask for this? Ignore this email and you won't hear from us again.`,
    html: emailShell('One tap to turn on your morning energy email.', `<h1 style="margin:0 0 12px;font-size:26px;line-height:1.2;font-weight:800">Confirm your morning email</h1><p style="margin:0 0 26px;font-size:17px;line-height:1.5;color:#4c6a62">Each morning we'll tell you the cleanest time to use electricity around <strong style="color:#10302a">${district}</strong>.</p>${emailButton(confirm, 'Yes, send me the email')}`, "Didn't ask for this? Ignore this email and you won't hear from us again."),
  }]);
  return ok ? reply(204, headers) : reply(502, headers, { error: 'not delivered' });
}

function alertPage(heading, text, button) {
  const html = `<!doctype html><html lang="en-GB"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${heading}</title><body style="font-family:system-ui,sans-serif;max-width:30rem;margin:3rem auto;padding:0 1rem;color:#10302a;line-height:1.5"><h1 style="font-size:1.5rem">${heading}</h1><p>${text}</p>${button ? `<form method="post"><button style="font:inherit;font-weight:600;color:#f2fbf7;background:#06704b;border:0;border-radius:999px;padding:.7rem 1.4rem;cursor:pointer">${button}</button></form>` : `<p><a href="${SITE_URL}" style="color:#06704b">Back to the site</a></p>`}</body></html>`;
  return new Response(html, { headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' } });
}

/* opening a link only shows a button: email scanners follow links automatically, and must not confirm or unsubscribe anyone */
async function alertConfirm(request, url, env) {
  if (request.method === 'GET') return alertPage('Turn on your morning email?', 'One email each morning. You can unsubscribe at any time.', 'Yes, turn it on');
  const done = await env.DB.prepare('UPDATE subscribers SET confirmed = 1 WHERE token = ?1').bind(url.searchParams.get('t') || '').run();
  return done.meta.changes ? alertPage("You're signed up", 'Your first email arrives tomorrow morning at about 07:30.') : alertPage('That link has expired', 'Please sign up again on the site.');
}

async function alertStop(request, url, env) {
  if (request.method === 'GET') return alertPage('Stop these emails?', 'This deletes your email address from our list.', 'Yes, unsubscribe me');
  await env.DB.prepare('DELETE FROM subscribers WHERE token = ?1').bind(url.searchParams.get('t') || '').run();
  return alertPage("You've been unsubscribed", 'Your email address has been deleted and you won\'t hear from us again.');
}

function bestWindow(rows, n, better) {
  let at = -1, score = null;
  for (let i = 0; i + n <= rows.length; i++) {
    const s = rows.slice(i, i + n).reduce((a, r) => a + r.g, 0);
    if (score === null || better(s, score)) { score = s; at = i; }
  }
  return at < 0 ? null : { from: rows[at].t, to: rows[at].t + n * SLOT, avg: score / n };
}

function whenWords(w, now) {
  const start = new Date(w.from);
  const day = ukDay.format(start) === ukDay.format(now) ? (Number(ukHour.format(start)) >= 18 ? 'tonight' : 'today') : 'tomorrow';
  return `${day}, ${ukClock.format(start)} to ${ukClock.format(new Date(w.to))}`;
}

function morningMail(sub, f, now) {
  const wash = bestWindow(f.rows, 5, (a, b) => a < b), car = bestWindow(f.rows, 12, (a, b) => a < b), worst = bestWindow(f.rows, 5, (a, b) => a > b);
  const flat = worst.avg - wash.avg < Math.max(5, worst.avg * 0.05);
  const link = `${SITE_URL}/?pc=${sub.district}`, stop = stopLink(sub.token);
  const lines = flat
    ? [`Power around ${sub.district} stays about as clean all day, so there's no need to plan around it today.`]
    : [`The cleanest times to use electricity around ${sub.district} in the next 24 hours:`, '', `Washing and other short jobs: ${whenWords(wash, now)}`, `Charging a car: ${whenWords(car, now)}`, `Try to avoid: ${whenWords(worst, now)}`];
  const row = (label, value, last) => `<tr><td style="padding:14px 0;${last ? '' : 'border-bottom:1px solid #dfeae6;'}"><div style="font-size:13px;font-weight:600;color:#4c6a62;padding-bottom:3px">${label}</div><div style="font-size:18px;font-weight:700;color:#10302a">${capital(value)}</div></td></tr>`;
  const inner = flat
    ? `<h1 style="margin:0 0 12px;font-size:26px;line-height:1.2;font-weight:800">Steady power today</h1><p style="margin:0 0 26px;font-size:17px;line-height:1.5;color:#4c6a62">Power around <strong style="color:#10302a">${sub.district}</strong> stays about as clean all day, so there's no need to plan around it.</p>`
    : `<p style="margin:0 0 6px;font-size:14px;font-weight:600;color:#4c6a62">Best time for washing and short jobs around ${sub.district}</p><h1 style="margin:0 0 14px;font-size:26px;line-height:1.2;font-weight:800">${capital(whenWords(wash, now))}</h1><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 24px">${row('Charging a car', whenWords(car, now))}${row('Try to avoid', whenWords(worst, now), true)}</table>`;
  return {
    to: [sub.email],
    html: emailShell(flat ? 'Power stays about as clean all day.' : `Cleanest power: ${whenWords(wash, now)}.`, inner + emailButton(link, 'See the full picture'), `An estimate from the national carbon forecast for ${escapeHtml(f.name)}.<br><a href="${stop}" style="color:#4c6a62">Unsubscribe</a>`),
    subject: flat ? `Power around ${sub.district} is steady today` : `Cleanest power around ${sub.district}: ${whenWords(wash, now)}`,
    text: `${lines.join('\n')}\n\nThe full picture: ${link}\n\nAn estimate from the national carbon forecast for ${f.name}.\n\nUnsubscribe: ${stop}`,
    headers: { 'List-Unsubscribe': `<${stop}>`, 'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click' },
  };
}

async function morningEmails(env) {
  const now = new Date();
  if (Number(ukHour.format(now)) !== 7 || !env.RESEND_KEY) return;
  if (!await underLimit(env, 'alerts-sent', 86400000, 1)) return;
  await env.DB.prepare('DELETE FROM subscribers WHERE confirmed = 0 AND created < ?1').bind(Date.now() - 7 * 86400000).run();
  const { results } = await env.DB.prepare('SELECT email, token, district, region FROM subscribers WHERE confirmed = 1 ORDER BY created').all();
  if (!results.length) return;
  const problems = [];
  if (results.length > DAILY_CAP) problems.push(`${results.length - DAILY_CAP} subscribers were skipped because the list is over the free daily limit of ${DAILY_CAP}.`);
  const from = new Date(Math.floor(Date.now() / SLOT) * SLOT).toISOString().slice(0, 16) + 'Z';
  const r = await fetch(`https://api.carbonintensity.org.uk/regional/intensity/${from}/fw24h`, { headers: { Accept: 'application/json' } });
  if (!r.ok) return telegram(env, `Morning emails were not sent: the forecast said ${r.status}.`);
  const regions = {};
  (await r.json()).data.forEach((slot) => slot.regions.forEach((x) => {
    (regions[x.regionid] = regions[x.regionid] || { name: x.shortname, rows: [] }).rows.push({ t: Date.parse(slot.from), g: x.intensity.forecast });
  }));
  const mails = results.slice(0, DAILY_CAP).filter((s) => regions[s.region] && regions[s.region].rows.length >= 12).map((s) => morningMail(s, regions[s.region], now));
  if (mails.length && !await sendEmails(env, mails)) problems.push('The email service refused today\'s morning emails.');
  if (problems.length) await telegram(env, problems.join('\n'));
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === 'GET' && url.pathname === '/stats') return stats(url, env);
    if (['GET', 'POST'].includes(request.method) && url.pathname === '/alerts/confirm') return alertConfirm(request, url, env);
    if (['GET', 'POST'].includes(request.method) && url.pathname === '/alerts/stop') return alertStop(request, url, env);
    const headers = cors(request, env);
    if (!headers) return new Response('Not found', { status: 404 });
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers });
    if (request.method === 'POST' && url.pathname === '/count') return count(request, env, headers);
    if (request.method === 'POST' && url.pathname === '/contact') return contact(request, env, headers);
    if (request.method === 'POST' && url.pathname === '/alerts') return alertSignup(request, env, headers);
    return reply(404, headers, { error: 'not found' });
  },
  async scheduled(event, env, ctx) {
    ctx.waitUntil(event.cron === ALERT_CRON ? morningEmails(env) : rebuild(env));
  },
};
