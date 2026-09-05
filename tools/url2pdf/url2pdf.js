#!/usr/bin/env node
'use strict';

const path = require('path');
const { chromium } = require('playwright');

function usageAndExit() {
  console.error('Usage: url2pdf <url> [output.pdf]');
  process.exit(1);
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
  const [rawUrl, outputArg] = process.argv.slice(2);
  if (!rawUrl) usageAndExit();

  const url = normalizeUrl(rawUrl);
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
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
