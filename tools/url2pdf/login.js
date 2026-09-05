#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const readline = require('readline');
const { chromium } = require('playwright');

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
  const statePath = path.join(STATES_DIR, `${stateName}.json`);

  fs.mkdirSync(STATES_DIR, { recursive: true });

  const browser = await chromium.launch({ headless: false });
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.goto(url);

    console.log('A browser window has opened. Log in there (including any email/OTP step).');
    await waitForEnter('Once you are logged in, press Enter here to save the session... ');

    await context.storageState({ path: statePath });
    console.log(`Session saved to ${statePath}`);
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});
