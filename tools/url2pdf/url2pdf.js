#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const STATES_DIR = path.join(__dirname, '.states');

function usageAndExit() {
  console.error('Usage: url2pdf <url> [output.pdf] [--state <state-name>]');
  process.exit(1);
}

function parseArgs(argv) {
  const args = { url: null, output: null, state: null };
  const positional = [];
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--state') {
      args.state = argv[++i];
    } else {
      positional.push(argv[i]);
    }
  }
  [args.url, args.output] = positional;
  return args;
}

function slugify(text) {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80) || 'page';
}

function normalizeUrl(input) {
  if (!/^https?:\/\//i.test(input)) {
    return `https://${input}`;
  }
  return input;
}

async function main() {
  const { url: rawUrl, output: outputArg, state: stateName } = parseArgs(process.argv.slice(2));
  if (!rawUrl) usageAndExit();

  let storageState;
  if (stateName) {
    const statePath = path.join(STATES_DIR, `${stateName}.json`);
    if (!fs.existsSync(statePath)) {
      console.error(`No saved session found at ${statePath}. Run: node login.js <url> ${stateName}`);
      process.exit(1);
    }
    storageState = statePath;
  }

  const url = normalizeUrl(rawUrl);
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext(storageState ? { storageState } : {});
    const page = await context.newPage();
    await page.goto(url, { waitUntil: 'networkidle' });

    let outputPath = outputArg;
    if (!outputPath) {
      const title = await page.title();
      const base = title ? slugify(title) : slugify(new URL(url).hostname + new URL(url).pathname);
      outputPath = `${base}.pdf`;
    }
    outputPath = path.resolve(process.cwd(), outputPath);

    await page.pdf({
      path: outputPath,
      printBackground: true,
      format: 'A4',
    });

    console.log(outputPath);
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});
