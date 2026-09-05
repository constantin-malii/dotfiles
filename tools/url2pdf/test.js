'use strict';

// Unit tests for url2pdf's own logic. Uses node:test (built in, no dependencies) and does NOT
// require Playwright -- the browser work is Playwright's to get right, not ours. What is tested
// here is argument handling and filename derivation, which is where the silent failures live.
//
// Run: node --test tools/url2pdf/

const test = require('node:test');
const assert = require('node:assert');

const { parseArgs, slugify, normalizeUrl, isSafeStateName, UsageError } = require('./url2pdf.js');

test('parseArgs: url and output', () => {
  const a = parseArgs(['example.com', 'out.pdf']);
  assert.strictEqual(a.url, 'example.com');
  assert.strictEqual(a.output, 'out.pdf');
  assert.strictEqual(a.state, null);
});

test('parseArgs: --state with a value', () => {
  const a = parseArgs(['example.com', '--state', 'wiki-example-com']);
  assert.strictEqual(a.state, 'wiki-example-com');
  assert.strictEqual(a.url, 'example.com');
});

test('parseArgs: --state with NO value must fail, not silently render logged out', () => {
  // The original bug: argv[++i] is undefined, which is falsy, so the auth branch was skipped
  // and a PDF of the login page was written with exit 0.
  assert.throws(() => parseArgs(['example.com', 'out.pdf', '--state']), UsageError);
});

test('parseArgs: --state=name is rejected rather than becoming the output filename', () => {
  assert.throws(() => parseArgs(['example.com', '--state=work']), UsageError);
});

test('parseArgs: a typo\'d flag is rejected rather than silently dropped', () => {
  assert.throws(() => parseArgs(['example.com', '--stat', 'work']), UsageError);
});

test('parseArgs: extra positional is rejected rather than discarded', () => {
  assert.throws(() => parseArgs(['example.com', 'out.pdf', 'extra']), UsageError);
});

test('parseArgs: --help is help, not a URL', () => {
  assert.strictEqual(parseArgs(['--help']).help, true);
  assert.strictEqual(parseArgs(['-h']).help, true);
});

test('parseArgs: a state name that escapes .states/ is rejected', () => {
  // .states/ is gitignored; ../work is not. This guard is what keeps live session cookies
  // out of a committable path.
  assert.throws(() => parseArgs(['example.com', '--state', '../work']), UsageError);
  assert.throws(() => parseArgs(['example.com', '--state', 'a/b']), UsageError);
});

test('isSafeStateName', () => {
  assert.ok(isSafeStateName('wiki-example-com'));
  assert.ok(isSafeStateName('work_1.2'));
  assert.ok(!isSafeStateName('../evil'));
  assert.ok(!isSafeStateName('a/b'));
  assert.ok(!isSafeStateName('.hidden'));
  assert.ok(!isSafeStateName(''));
});

test('slugify: strips path separators and never yields an empty name', () => {
  assert.strictEqual(slugify('Foo / Bar'), 'foo-bar');
  assert.strictEqual(slugify('../../etc/passwd'), 'etc-passwd');
  // An all-non-Latin title has no usable slug and falls back rather than producing "".
  assert.strictEqual(slugify('日本語のページ'), 'page');
  assert.strictEqual(slugify('•••'), 'page');
});

test('slugify: caps length without leaving a trailing dash', () => {
  const out = slugify('a'.repeat(200));
  assert.ok(out.length <= 80);
  assert.ok(!out.endsWith('-'));
});

test('normalizeUrl: bare domain gets https', () => {
  assert.strictEqual(normalizeUrl('example.com'), 'https://example.com');
  assert.strictEqual(normalizeUrl('http://example.com'), 'http://example.com');
  assert.strictEqual(normalizeUrl('HTTPS://example.com'), 'HTTPS://example.com');
});
