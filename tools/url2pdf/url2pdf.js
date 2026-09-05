#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
// Loaded lazily inside main(): a missing dependency would otherwise be a raw Node stack trace at
// require time, and keeping it out of module scope lets the pure argument logic be unit-tested
// without Playwright installed. Setup is manual per CLAUDE.md, so "not installed" is the expected
// state of every fresh machine.
function loadChromium() {
  try {
    return require('playwright').chromium;
  } catch (err) {
    if (err.code !== 'MODULE_NOT_FOUND') throw err;
    throw new UsageError(
      'Playwright is not installed. Run:' +
      String.fromCharCode(10) +
      `  cd ${__dirname} && npm install && npx playwright install chromium`
    );
  }
}

const STATES_DIR = path.join(__dirname, '.states');
const USAGE = 'Usage: url2pdf <url> [output.pdf] [--state <state-name>]';

// Thrown for anything the user can fix by retyping the command. main()'s catch turns it into a
// one-line message and exit 1, so argument handling stays pure and testable.
class UsageError extends Error {}

// A state name becomes a filename under .states/, which is the ONLY thing keeping live session
// cookies out of git -- the root .gitignore's *token*/*secret*/*key* patterns do not match these
// names. An unvalidated name containing ".." writes the credential outside that ignore.
function isSafeStateName(stateName) {
  return /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(stateName) && !stateName.includes('..');
}

function parseArgs(argv) {
  const args = { url: null, output: null, state: null, help: false };
  const positional = [];
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--state') {
      // Without this check a trailing "--state" yields undefined, which is falsy, so the auth
      // branch in main() is skipped and the page renders logged OUT -- reported as success.
      if (i + 1 >= argv.length) {
        throw new UsageError('--state requires a session name, e.g. --state wiki-example-com');
      }
      args.state = argv[++i];
      if (!isSafeStateName(args.state)) {
        throw new UsageError(
          `invalid state name "${args.state}". Use letters, digits, dots, dashes or underscores only.`
        );
      }
    } else if (argv[i] === '-h' || argv[i] === '--help') {
      args.help = true;
      return args;
    } else if (argv[i].startsWith('--')) {
      throw new UsageError(`unknown option ${argv[i]}`);
    } else {
      positional.push(argv[i]);
    }
  }
  if (positional.length > 2) {
    throw new UsageError(`unexpected extra argument "${positional[2]}"`);
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
  const { url: rawUrl, output: outputArg, state: stateName, help } = parseArgs(process.argv.slice(2));
  if (help) {
    console.log(USAGE);
    return;
  }
  if (!rawUrl) throw new UsageError(USAGE);

  let storageState;
  if (stateName) {
    const statePath = path.join(STATES_DIR, `${stateName}.json`);
    if (!fs.existsSync(statePath)) {
      console.error(`No saved session found at ${statePath}. Run: url2pdf-login <url> ${stateName}`);
      process.exit(1);
    }
    storageState = statePath;
  }

  const url = normalizeUrl(rawUrl);
  const chromium = loadChromium();
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext(storageState ? { storageState } : {});
    const page = await context.newPage();
    // goto does NOT throw on an HTTP error status -- only on transport failure. Without this
    // check a 404, a 500 or a proxy block page renders to PDF and exits 0.
    const response = await page.goto(url, { waitUntil: 'networkidle' });
    if (response && !response.ok()) {
      console.error(
        `url2pdf: ${url} returned HTTP ${response.status()} ${response.statusText()}. ` +
        'No PDF written.'
      );
      process.exit(1);
    }

    // A saved session that has expired redirects to a login wall, which would otherwise be
    // captured as a perfectly valid-looking PDF.
    if (stateName && new URL(page.url()).host !== new URL(url).host) {
      console.error(
        `url2pdf: ${url} redirected to ${page.url()} -- the saved session "${stateName}" has ` +
        `probably expired. Re-run: url2pdf-login ${new URL(url).host} ${stateName}`
      );
      process.exit(1);
    }

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
    // A rejection thrown from finally DISCARDS the in-flight exception. Closing the browser
    // window by hand is the natural instinct after logging in, and it makes close() reject --
    // which would otherwise hide whatever actually went wrong.
    await browser.close().catch((e) => {
      console.error(`url2pdf: warning -- browser cleanup failed: ${e.message}`);
    });
  }
}

if (require.main === module) {
  main().catch((err) => {
    console.error(err instanceof UsageError ? `url2pdf: ${err.message}` : (err.message || err));
    process.exit(1);
  });
}

module.exports = { parseArgs, slugify, normalizeUrl, isSafeStateName, UsageError };
