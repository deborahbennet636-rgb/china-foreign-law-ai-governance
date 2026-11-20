#!/usr/bin/env node
/**
 * Open dist/index.html in headless Chrome, visit each view, collect page
 * errors and take screenshots. Uses its own temporary profile and port.
 * Output: temp/shots/*.png and temp/shots/report.json
 *
 * Needs the `ws` package; set WS_MODULE to its path if it is not installed
 * next to this script.
 */
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const http = require('http');
const { pathToFileURL } = require('url');
const WebSocket = require(process.env.WS_MODULE || 'ws');

const PORT = 9347;
const CHROME = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const ROOT = path.join(__dirname, '..');
const OUT = path.join(ROOT, 'temp', 'shots');
const TARGET = pathToFileURL(path.join(ROOT, 'dist', 'index.html')).href;
const ROUTES = [
  ['issues', '#/issues'],
  ['issue', '#/issue/ISSUE-TRAINING-COPYRIGHT'],
  ['issue-personality', '#/issue/ISSUE-PERSONALITY-DEEPFAKE'],
  ['instruments', '#/instruments'],
  ['instrument-cn', '#/instrument/CN-SPC-AI-OPINION-2026/' + encodeURIComponent('（十二）')],
  ['instrument-eu', '#/instrument/EU-AI-ACT-2024/' + encodeURIComponent('Article 50')],
  ['instrument-meta-only', '#/instrument/EU-OMNIBUS-AI-2026'],
  ['cases', '#/cases'],
  ['case-cn', '#/case/CN-CASE-RAG-SEARCH'],
  ['case-judgment', '#/case/CN-CASE-AI-VOICE'],
  ['case-judgment-2', '#/case/CN-CASE-AI-IMAGE-AUTHORSHIP'],
  ['instrument-civil', '#/instrument/CN-CIVIL-CODE/' + encodeURIComponent('第一千零二十三条')],
  ['case-us', '#/case/US-CASE-BARTZ-V-ANTHROPIC'],
  ['leads', '#/leads'],
  ['sources', '#/sources'],
  ['about', '#/about'],
  ['search', '#/search/' + encodeURIComponent('合理使用')],
  ['search-en', '#/search/' + encodeURIComponent('fair use')],
  ['search-none', '#/search/' + encodeURIComponent('量子计算')],
  ['missing', '#/case/NO-SUCH-CASE'],
  ['bad-escape', '#/search/%E0%A4%A'],
];

fs.mkdirSync(OUT, { recursive: true });
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'aigov-shot-'));
const chrome = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  '--no-first-run', '--no-default-browser-check', '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const getJSON = (route) => new Promise((resolve, reject) => {
  http.get(`http://127.0.0.1:${PORT}${route}`, (response) => {
    let body = '';
    response.on('data', (chunk) => { body += chunk; });
    response.on('end', () => { try { resolve(JSON.parse(body)); } catch (error) { reject(error); } });
  }).on('error', reject);
});

async function debuggerUrl() {
  for (let attempt = 0; attempt < 60; attempt++) {
    try {
      const target = (await getJSON('/json/list')).find((item) => item.type === 'page');
      if (target) return target.webSocketDebuggerUrl;
    } catch (error) { /* Chrome is still starting */ }
    await sleep(250);
  }
  throw new Error('Chrome did not start');
}

async function main() {
  const socket = new WebSocket(await debuggerUrl());
  await new Promise((resolve) => socket.on('open', resolve));
  let nextId = 0;
  const waiting = new Map();
  const problems = [];
  socket.on('message', (raw) => {
    const message = JSON.parse(raw);
    if (message.id && waiting.has(message.id)) { waiting.get(message.id)(message.result || message); waiting.delete(message.id); }
    if (message.method === 'Runtime.exceptionThrown') problems.push('exception: ' + (message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text));
    if (message.method === 'Log.entryAdded' && ['error', 'warning'].includes(message.params.entry.level)) problems.push(message.params.entry.level + ': ' + message.params.entry.text);
    if (message.method === 'Network.requestWillBeSent' && !message.params.request.url.startsWith('file:')) problems.push('network request: ' + message.params.request.url);
  });
  const send = (method, params = {}) => new Promise((resolve) => { const id = ++nextId; waiting.set(id, resolve); socket.send(JSON.stringify({ id, method, params })); });
  const evaluate = async (expression) => (await send('Runtime.evaluate', { expression, returnByValue: true })).result?.value;

  for (const domain of ['Page', 'Runtime', 'Log', 'Network']) await send(`${domain}.enable`);
  await send('Emulation.setDeviceMetricsOverride', { width: 1360, height: 900, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: TARGET });
  await sleep(900);

  const report = [];
  for (const [name, hash] of ROUTES) {
    await evaluate(`location.hash = ${JSON.stringify(hash)}`);
    await sleep(350);
    const info = await evaluate(`JSON.stringify({
      h1: document.querySelector('#view h1')?.textContent,
      chars: document.querySelector('#view').textContent.length,
      cards: document.querySelectorAll('#view .card, #view .lead, #view .prov, #view tr').length,
      seals: Array.from(document.querySelectorAll('#view .seal')).reduce((m, n) => (m[n.textContent] = (m[n.textContent] || 0) + 1, m), {}),
      current: document.querySelector('#nav a[aria-current]')?.textContent,
      overflow: document.documentElement.scrollWidth > window.innerWidth,
      hit: !!document.querySelector('#view .prov.hit')
    })`);
    report.push({ name, hash, ...JSON.parse(info) });
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(OUT, `${name}.png`), Buffer.from(shot.data, 'base64'));
  }

  // The search box must route through the form, and a narrow screen must not scroll sideways.
  await evaluate(`document.getElementById('q').value = '声音'; document.getElementById('search-form').requestSubmit()`);
  await sleep(350);
  const viaForm = await evaluate(`location.hash + ' | ' + document.querySelector('#view h1').textContent`);
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  await evaluate(`location.hash = '#/issue/ISSUE-PROVIDER-LIABILITY'`);
  await sleep(350);
  const narrowOverflow = await evaluate(`document.documentElement.scrollWidth > window.innerWidth`);
  const narrow = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(OUT, 'narrow.png'), Buffer.from(narrow.data, 'base64'));

  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify({ report, viaForm, narrowOverflow, problems }, null, 1));
  for (const row of report) console.log(`${row.name.padEnd(22)} h1=${row.h1} | chars=${row.chars} nodes=${row.cards} seals=${JSON.stringify(row.seals)} nav=${row.current}${row.overflow ? ' OVERFLOW' : ''}${row.hit ? ' [target highlighted]' : ''}`);
  console.log('form search ->', viaForm);
  console.log('narrow overflow:', narrowOverflow);
  console.log('problems:', problems.length ? problems : 'none');
  socket.close();
  return problems.length ? 1 : 0;
}

main().then((code) => { process.exitCode = code; }).catch((error) => { console.error(error); process.exitCode = 1; }).finally(() => {
  chrome.kill();
  setTimeout(() => { try { fs.rmSync(profile, { recursive: true, force: true }); } catch (error) { /* profile is still locked; the OS temp cleaner takes it */ } }, 500);
});
