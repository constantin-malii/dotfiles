#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const readline = require('readline');
// Required at load, so a missing dependency would otherwise surface as a raw Node stack trace.
// Setup is manual per CLAUDE.md, so "not installed" is the expected state of every fresh machine.
let chromium;
try {
  ({ chromium } = require('playwright'));
} catch (err) {
  if (err.code !== 'MODULE_NOT_FOUND') throw err;
  console.error('Playwright is not installed. Run:');
  console.error(`  cd ${__dirname} && npm install && npx playwright install chromium`);
  process.exit(1);
}

const STATES_DIR = path.join(__dirname, '.states');

function usageAndExit() {
  console.error('Usage: login.js <url> [state-name]');
  process.exit(1);
}

function normalizeUrl(input) {
  if (!/^https?:\/\//i.test(input)) {
    return `https://${input}`;
  }
  return input;
}

// See the matching guard in url2pdf.js: an unvalidated name escapes .states/ and therefore
// escapes the only .gitignore rule protecting these credential files.
function assertSafeStateName(stateName) {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(stateName) || stateName.includes('..')) {
    console.error(
      `login.js: invalid state name "${stateName}". ` +
      'Use letters, digits, dots, dashes or underscores only.'
    );
    process.exit(1);
  }
}

function slugifyHostname(hostname) {
  return hostname.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

function waitForEnter(promptText) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => {
    rl.question(promptText, () => {
      rl.close();
      resolve();
    });
  });
}

async function main() {
  const [rawUrl, stateNameArg] = process.argv.slice(2);
  if (!rawUrl) usageAndExit();

  const url = normalizeUrl(rawUrl);
  const stateName = stateNameArg || slugifyHostname(new URL(url).hostname);
  assertSafeStateName(stateName);
  const statePath = path.join(STATES_DIR, `${stateName}.json`);

  // 0700/0600: this directory holds live session cookies in cleartext.
  fs.mkdirSync(STATES_DIR, { recursive: true, mode: 0o700 });

  const browser = await chromium.launch({ headless: false });
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.goto(url);

    console.log('A browser window has opened. Log in there (including any email/OTP step).');
    console.log('Leave that window OPEN -- closing it discards the session before it can be saved.');
    await waitForEnter('Once you are logged in, press Enter here to save the session... ');

    // storageState() cannot fail on "the user never logged in" -- it happily serialises an empty
    // session. Reporting success for that leaves a file that looks valid to url2pdf, which then
    // renders login pages for weeks. Verify, and delete rather than leave a decoy.
    await context.storageState({ path: statePath });
    try {
      fs.chmodSync(statePath, 0o600);
    } catch (e) {
      console.error(`login.js: warning -- could not restrict permissions on ${statePath}: ${e.message}`);
    }
    const saved = JSON.parse(fs.readFileSync(statePath, 'utf8'));
    const cookieCount = (saved.cookies || []).length;
    const originCount = (saved.origins || []).length;
    if (cookieCount === 0 && originCount === 0) {
      fs.unlinkSync(statePath);
      console.error(
        `login.js: no cookies or local storage were captured for ${url}, so nothing was saved. ` +
        'This usually means Enter was pressed before the login finished. Re-run and press Enter ' +
        'only once the logged-in page has fully loaded.'
      );
      process.exit(1);
    }
    console.log(`Session saved to ${statePath} (${cookieCount} cookies, ${originCount} origins)`);
  } finally {
    // A rejection thrown from finally DISCARDS the in-flight exception. Closing the browser
    // window by hand is the natural instinct after logging in, and it makes close() reject --
    // which would otherwise hide whatever actually went wrong.
    await browser.close().catch((e) => {
      console.error(`login.js: warning -- browser cleanup failed: ${e.message}`);
    });
  }
}

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});
