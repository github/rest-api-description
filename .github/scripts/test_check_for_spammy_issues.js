const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');

const workflow = readFileSync(
  path.join(__dirname, '../workflows/check-for-spammy-issues.yml'),
  'utf8',
);
const script = workflow.split('          script: |\n')[1];
assert.ok(script, 'The workflow must include its github-script body');
const preprocessing = script.slice(0, script.indexOf('let bodyWordCount = 0'));
const preprocess = new Function(
  'context',
  `${preprocessing}\nreturn body;`,
);

function stripBody(body) {
  return preprocess({ payload: { issue: { title: 'Too short', body } } });
}

const harness = `
  const { readFileSync } = require('node:fs');
  const input = JSON.parse(readFileSync(0, 'utf8'));
  const calls = [];
  const context = {
    payload: {
      issue: { number: 42, title: input.title, body: input.body },
      sender: { login: 'reporter' },
    },
  };
  const github = {
    teams: {
      async getMembershipForUserInOrg() {
        if (!input.employee) throw new Error('Not a team member');
      },
    },
    issues: {
      async update(params) { calls.push({ method: 'update', params }); },
      async createComment(params) { calls.push({ method: 'createComment', params }); },
    },
  };
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  new AsyncFunction('github', 'context', input.script)(github, context)
    .then(() => process.stdout.write(JSON.stringify(calls)))
    .catch(error => {
      console.error(error);
      process.exitCode = 1;
    });
`;

function runWorkflow(body, { title = 'Too short', employee = false } = {}) {
  const result = spawnSync(process.execPath, ['-e', harness], {
    input: JSON.stringify({ script, body, title, employee }),
    encoding: 'utf8',
    timeout: 2000,
  });
  assert.ifError(result.error);
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

function assertClosed(body, options) {
  const calls = runWorkflow(body, options);
  assert.deepEqual(calls.map(call => call.method), ['update', 'createComment']);
  assert.deepEqual(calls[0].params, {
    owner: 'github',
    repo: 'rest-api-description',
    issue_number: 42,
    labels: ['invalid'],
    state: 'closed',
  });
  assert.equal(calls[1].params.issue_number, 42);
}

test('closes issues with short titles and bodies', () => {
  assertClosed('Not enough detail');
});

test('accepts a descriptive title', () => {
  assert.deepEqual(runWorkflow('', { title: 'A descriptive issue title' }), []);
});

test('accepts a descriptive body', () => {
  assert.deepEqual(runWorkflow('This issue contains enough words to explain the problem'), []);
});

test('does not count template comments or indented headings as body words', () => {
  assertClosed('<!--- These template words should not count -->\n  # This heading should not count either\nToo short');
});

test('preserves descriptive text between headings', () => {
  assert.deepEqual(
    runWorkflow('# First heading\nThis issue contains enough words to explain the problem\n## Next heading\n'),
    [],
  );
});

test('preserves a heading without a trailing newline', () => {
  assert.deepEqual(runWorkflow('# These heading words alone should keep an issue open'), []);
});

test('handles CRLF headings and body text', () => {
  assertClosed(' \t## These heading words should not count\r\nToo short\r\n');
  assert.deepEqual(
    runWorkflow('# Heading\r\nThis issue contains enough words to explain the problem\r\n'),
    [],
  );
});

test('keeps hash characters that are not at the start of a line', () => {
  assert.deepEqual(runWorkflow('This body refers to #123 and explains the problem'), []);
});

test('preserves empty body handling', () => {
  assertClosed('');
});

test('does not change unsupported null or missing body handling', () => {
  for (const body of [null, undefined]) {
    assert.throws(() => stripBody(body), TypeError);
  }
});

test('leaves employee issues open', () => {
  assert.deepEqual(runWorkflow('', { employee: true }), []);
});

test('still rejects the unchanged schema template title', () => {
  assertClosed('This issue contains enough words to explain the problem', {
    title: '[Schema Inaccuracy] <Describe Problem>',
  });
});

test('handles a maximum-length heading followed by whitespace within two seconds', () => {
  assertClosed('#' + ' '.repeat(65535));
});

test('handles maximum-length whitespace before a heading within two seconds', () => {
  assertClosed(' '.repeat(65534) + '#x');
});

test('preserves legacy whitespace, end-of-file, and multiline matching', () => {
  const fixtures = [
    ['', ''],
    ['# Heading', '# Heading'],
    ['# Heading\n', ''],
    ['#\n', '#\n'],
    ['# \n', ''],
    ['#\n\n', '#\n\n'],
    ['#\n \n', ''],
    ['#\nContent\n', ''],
    ['#\nContent', '#\nContent'],
    ['# \nContent', 'Content'],
    ['# Heading\nContent', 'Content'],
    ['# Heading\n\n \nContent', 'Content'],
    ['\n \n# Heading\n \n \nContent', 'Content'],
    ['# Heading\rContent\n', '# Heading\rContent\n'],
    ['# Heading\u2028Content\n', '# Heading\u2028Content\n'],
    ['# Heading\u2029Content\n', '# Heading\u2029Content\n'],
    ['# Heading\r\nContent\r\n', 'Content\r\n'],
    ['# Heading\r\n \r\nContent', 'Content'],
    ['Content\n# Heading\n', 'Content\n'],
    ['Content\r# Heading\n', 'Content\r'],
    ['\t#\tHeading\t\n\t\nContent', 'Content'],
    ['<!--- Hidden words -->\n# Heading\nContent', 'Content'],
  ];
  for (const [body, expected] of fixtures) {
    assert.equal(stripBody(body), expected, JSON.stringify(body));
  }
});

test('preserves template decisions and exact title/body thresholds', () => {
  const template = readFileSync(
    path.join(__dirname, '../ISSUE_TEMPLATE/schema-inaccuracy.md'),
    'utf8',
  ).split('\n---\n')[1];
  assert.ok(template);
  assertClosed(template, { title: '[Schema Inaccuracy] <Describe Problem>' });
  assert.deepEqual(runWorkflow(template, { title: 'A descriptive issue title' }), []);
  assertClosed('one two three four five');
  assert.deepEqual(runWorkflow('one two three four five six'), []);
  assertClosed('', { title: 'two words' });
  assert.deepEqual(runWorkflow('', { title: 'three title words' }), []);
  assertClosed('#\nThis issue contains enough words to explain the problem\n');
});

test('handles maximum-length blank lines and multiple headings within two seconds', () => {
  assertClosed('\n'.repeat(65536));
  assertClosed('# \n'.repeat(21845));
  assertClosed('#\r'.repeat(32768));
  assertClosed('#' + '\r'.repeat(65535));
});
