import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';

const task = mkdtempSync(join(process.env.TASK_TEMP ?? tmpdir(), 'codex-node-pack-'));
const npm = process.env.npm_execpath;
assert.ok(npm, 'invoke through npm run test:package');
const runNpm = args => execFileSync(process.execPath, [npm, ...args], { encoding: 'utf8', timeout: 60000 });
try {
  const metadata = JSON.parse(readFileSync('package.json'));
  assert.equal(metadata.private, true);
  assert.deepEqual(metadata.dependencies, { 'fs-ext-extra-prebuilt': '2.2.14' });
  for (const hook of ['preinstall', 'install', 'postinstall', 'prepare', 'prepack']) {
    assert.equal(metadata.scripts[hook], undefined);
  }
  assert.match(readFileSync('LICENSE', 'utf8'), /MIT License/);
  assert.equal(execFileSync(process.execPath, ['dist/cli.js', '--version'], { encoding: 'utf8' }).trim(), `${metadata.name} ${metadata.version}`);
  let hash;
  for (let index = 0; index < 2; index++) {
    const [packed] = JSON.parse(runNpm(['pack', '--ignore-scripts', '--json', '--pack-destination', task]));
    assert.deepEqual(packed.files.map(file => file.path).sort(), ['LICENSE', 'README.md', 'dist/cli.js', 'dist/discovery.js', 'dist/process.js', 'dist/protocol.js', 'dist/send.js', 'dist/writer.js', 'package.json']);
    const next = createHash('sha256').update(readFileSync(join(task, packed.filename))).digest('hex');
    if (hash) assert.equal(next, hash, 'same build must produce identical tarball');
    hash = next;
  }
  const prefix = join(task, 'install');
  const home = join(task, 'empty-home');
  mkdirSync(home);
  runNpm(['install', '--prefix', prefix, '--ignore-scripts', '--no-audit', '--no-fund', join(task, `${metadata.name}-${metadata.version}.tgz`)]);
  const binary = join(prefix, 'node_modules/.bin/session-peer-ts');
  assert.ok(statSync(binary).mode & 0o111);
  const result = JSON.parse(execFileSync(process.execPath, [binary, 'list', '--agent', 'claude', '--json'], {
    encoding: 'utf8', timeout: 10000,
    env: { ...process.env, PATH: '', HOME: home, CLAUDE_CONFIG_DIR: join(home, '.claude'), ANTHROPIC_CONFIG_DIR: '' }
  }));
  assert.equal(result.ok, true);
  assert.deepEqual(result.sessions, []);
  runNpm(['uninstall', '--prefix', prefix, '--ignore-scripts', '--no-audit', '--no-fund', metadata.name]);
  assert.equal(existsSync(binary), false);
  assert.equal(existsSync(join(prefix, 'node_modules', metadata.name)), false);
  console.log(JSON.stringify({ packageSmoke: 'pass', reproducibleSha256: hash, cleanInstall: true, uninstall: true }));
} finally {
  rmSync(task, { recursive: true });
}
