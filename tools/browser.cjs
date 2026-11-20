#!/usr/bin/env node
/**
 * Minimal browser session for sites that need a real browser (subscription
 * databases reached over the campus network). Uses its own temporary
 * profile and port, so the user's own Chrome is not touched.
 *
 *   node tools/browser.cjs start [url]        launch Chrome in the background
 *   node tools/browser.cjs goto <url>         navigate the tab and wait for load
 *   node tools/browser.cjs eval <js>          evaluate an expression, print the result
 *   node tools/browser.cjs save <css> <file>  write an element's HTML to a file
 *   node tools/browser.cjs stop               close the browser
 *
 * VISIBLE=1 opens a normal window, for pages where the user has to pass a
 * verification or log in by hand. The site's checks are left to the user.
 * Needs the `ws` package; set WS_MODULE to its path if it is not installed
 * next to this script.
 */
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const http = require('http');
const WebSocket = require(process.env.WS_MODULE || 'ws');

const PORT = 9351;
const CHROME = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PROFILE = path.join(os.tmpdir(), 'aigov-browser-profile');
const HTML_PREFIX = '<!doctype html><meta charset="utf-8">';
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function getJSON(route) {
  return new Promise((resolve, reject) => {
    http.get(`http://127.0.0.1:${PORT}${route}`, (response) => {
      let body = '';
      response.on('data', (chunk) => { body += chunk; });
      response.on('end', () => { try { resolve(JSON.parse(body)); } catch (error) { reject(error); } });
    }).on('error', reject);
  });
}

async function page() {
  for (let attempt = 0; attempt < 40; attempt++) {
    try {
      const target = (await getJSON('/json/list')).find((item) => item.type === 'page');
      if (target) return target;
    } catch (error) { /* not up yet */ }
    await sleep(250);
  }
  throw new Error('browser is not running; run: node tools/browser.cjs start');
}

async function withSocket(run) {
  const target = await page();
  const socket = new WebSocket(target.webSocketDebuggerUrl, { perMessageDeflate: false });
  await new Promise((resolve, reject) => { socket.on('open', resolve); socket.on('error', reject); });
  let nextId = 0;
  const waiting = new Map();
  socket.on('message', (raw) => {
    const message = JSON.parse(raw);
    if (message.id && waiting.has(message.id)) { waiting.get(message.id)(message); waiting.delete(message.id); }
  });
  const send = (method, params = {}) => new Promise((resolve) => {
    const id = ++nextId;
    waiting.set(id, resolve);
    socket.send(JSON.stringify({ id, method, params }));
  });
  try { return await run(send); } finally { socket.close(); }
}

async function evaluate(send, expression) {
  const reply = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (reply.result.exceptionDetails) {
    throw new Error('page exception: ' + JSON.stringify(reply.result.exceptionDetails.exception || reply.result.exceptionDetails.text));
  }
  return (reply.result.result || {}).value;
}

async function main() {
  const [command, argument, extra] = process.argv.slice(2);
  if (command === 'start') {
    fs.mkdirSync(PROFILE, { recursive: true });
    const mode = process.env.VISIBLE === '1' ? [] : ['--headless=new'];
    const child = spawn(CHROME, [...mode, `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
      '--no-first-run', '--no-default-browser-check', '--window-size=1400,1000', argument || 'about:blank'], { detached: true, stdio: 'ignore' });
    child.unref();
    await page();
    console.log('started on port', PORT);
  } else if (command === 'goto') {
    await withSocket(async (send) => {
      await send('Page.enable');
      await send('Page.navigate', { url: argument });
      await sleep(Number(process.env.WAIT_MS || 6000));
      console.log(await evaluate(send, 'location.href + " | " + document.title'));
    });
  } else if (command === 'eval') {
    await withSocket(async (send) => {
      const value = await evaluate(send, argument);
      console.log(typeof value === 'string' ? value : JSON.stringify(value, null, 1));
    });
  } else if (command === 'save') {
    await withSocket(async (send) => {
      const html = await evaluate(send, `(() => { const node = document.querySelector(${JSON.stringify(argument)}); return node ? node.outerHTML : null; })()`);
      if (!html) { console.log('element not found:', argument); process.exitCode = 1; return; }
      fs.writeFileSync(extra, HTML_PREFIX + '\n' + html + '\n', 'utf8');
      console.log('saved', html.length, 'chars ->', extra);
    });
  } else if (command === 'stop') {
    await withSocket((send) => send('Browser.close')).catch(() => {});
    console.log('stopped');
  } else {
    console.log('usage: start [url] | goto <url> | eval <js> | save <css> <file> | stop');
  }
}

main().catch((error) => { console.error(error.message); process.exitCode = 1; });
