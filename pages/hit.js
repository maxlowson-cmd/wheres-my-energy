/* Counts page opens and where visitors came from. Plain daily totals: no cookies, nothing stored on the device, nothing that identifies anyone. */
(function () {
  var API = 'https://wheres-my-energy-relay.wheresmyenergy.workers.dev';
  var home = location.hostname.replace(/^www\./, '');
  if (home !== 'wheresmyenergyfrom.co.uk' || navigator.webdriver) return;
  var nav = performance.getEntriesByType ? performance.getEntriesByType('navigation')[0] : null;
  if (nav && nav.type === 'reload') return;
  var host = '';
  try { host = new URL(document.referrer).hostname.replace(/^www\./, ''); } catch (e) {}
  var ua = navigator.userAgent, from = '';
  if (host !== home && !(nav && nav.type === 'back_forward')) {
    from = /Instagram/.test(ua) || /instagram\.com$/.test(host) ? 'instagram'
      : /FBAN|FBAV/.test(ua) || /(facebook\.com|fb\.me)$/.test(host) ? 'facebook'
      : /(google|bing|duckduckgo|yahoo|ecosia|brave)\./.test(host) ? 'search'
      : /(^t\.co|twitter\.com|^x\.com)$/.test(host) ? 'x'
      : /whatsapp/.test(host) ? 'whatsapp'
      : /(^t\.me|telegram)/.test(host) ? 'telegram'
      : /reddit\.com$/.test(host) ? 'reddit'
      : /tiktok\.com$/.test(host) ? 'tiktok'
      : /linkedin\.com$|^lnkd\.in$/.test(host) ? 'linkedin'
      : host ? 'other' : 'direct';
  }
  fetch(API + '/hit', { method: 'POST', keepalive: true, body: JSON.stringify({ e: 'view', d: document.currentScript ? document.currentScript.dataset.page : 'home', s: from }) }).catch(function () {});
})();
