// Contract first: the Python v1 fixture and production CLI are the oracle.
// Only temporary records/SQLite databases/Unix sockets; never real agent homes.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'node:net';

const root = fileURLToPath(new URL('../../../', import.meta.url));
const cli = fileURLToPath(new URL('../dist/cli.js', import.meta.url));
const fixture = JSON.parse(readFileSync(join(root, 'tests/fixtures/compatibility-v1.json')));
const python = process.env.PYTHON ?? 'python3';

function sandbox(t) {
  const path = mkdtempSync(join(process.env.TASK_TEMP ?? tmpdir(), 'codex-node-cli-'));
  mkdirSync(join(path, '.claude/sessions'), { recursive: true });
  const env = { ...process.env, HOME: path, USERPROFILE: path,
    CLAUDE_CONFIG_DIR: join(path, '.claude'), ANTHROPIC_CONFIG_DIR: '',
    CODEX_HOME: '', SESSION_PEER_CODEX_HOMES: '', PYTHONDONTWRITEBYTECODE: '1' };
  t.after(() => rmSync(path, { recursive: true }));
  return { path, env };
}
function invoke(binary, args, env) {
  const result = spawnSync(binary, args, { env, encoding: 'utf8', timeout: 10000 });
  assert.ifError(result.error);
  assert.equal(result.signal, null, result.stderr);
  const value = JSON.parse(result.stdout);
  for (const [key, type] of Object.entries(fixture.jsonResult.required)) {
    assert.equal(typeof value[key], { int: 'number', bool: 'boolean', str: 'string' }[type]);
  }
  assert.equal(value.schemaVersion, fixture.schemaVersion);
  return { status: result.status, value, stderr: result.stderr };
}
function compare(args, env) {
  const node = invoke(process.execPath, [cli, ...args, '--json'], env);
  const reference = invoke(python, [join(root, 'session_peer.py'), ...args, '--json', '--no-update-notice'], env);
  assert.equal(node.status, reference.status);
  // Package version is independent; only the explicitly supported projection is compared.
  assert.equal(node.value.ok, reference.value.ok);
  assert.equal(node.value.command, reference.value.command);
  assert.equal(node.value.host, reference.value.host);
  assert.deepEqual(node.value.sessions, reference.value.sessions);
  return { node, reference };
}

test('Claude empty and stale records match Python, without creating homes', t => {
  const { path, env } = sandbox(t);
  compare(['list', '--agent', 'claude'], env);
  const records = join(path, '.claude/sessions');
  writeFileSync(join(records, '1.json'), JSON.stringify({ pid: 1, name: 'stale' }));
  writeFileSync(join(records, '2.json'), JSON.stringify({ pid: process.pid, name: 'mismatched' }));
  writeFileSync(join(records, '3.json'), '{broken');
  writeFileSync(join(records, 'not-a-pid.json'), '{}');
  compare(['list', '--agent', 'claude'], env);
  compare(['list', '--agent', 'claude', '--all'], env);
  assert.deepEqual(readdirSync(path), ['.claude']);
});

test('actual Unix socket metadata matches Python but no connection is made', async t => {
  const { path, env } = sandbox(t);
  const socketDir = mkdtempSync(join(process.env.TASK_TEMP ?? tmpdir(), 'codex-socket-'));
  const socket = join(socketDir, 's');
  let connections = 0;
  const server = createServer(s => { connections++; s.destroy(); });
  await new Promise((ok, fail) => { server.once('error', fail); server.listen(socket, ok); });
  t.after(async () => { await new Promise(ok => server.close(ok)); rmSync(socketDir, { recursive: true }); });
  writeFileSync(join(path, '.claude/sessions', `${process.pid}.json`), JSON.stringify({
    pid: process.pid, name: '한글 🚀', messagingSocketPath: socket, cwd: '/fixture', status: 'idle'
  }));
  const { node } = compare(['list', '--agent', 'claude'], env);
  assert.equal(node.value.sessions[0].reachable, true);
  await new Promise(ok => setImmediate(ok));
  assert.equal(connections, 0);
});

function makeDatabase(home, withName = true) {
  mkdirSync(home);
  const code = `import sqlite3,sys\np=sys.argv[1]\nc=sqlite3.connect(p)\nc.execute("CREATE TABLE threads(id TEXT,title TEXT,cwd TEXT,updated_at INTEGER,archived INTEGER,rollout_path TEXT${withName ? ',name TEXT' : ''})")\nrows=[('b','title\\nsecond','/fixture',9,0,'unused'${withName ? ",''" : ''}),('a','🚀'*130,'/fixture',9,0,'unused'${withName ? ",None" : ''}),('z','archived','/fixture',10,1,'unused'${withName ? ",'named'" : ''})]\nc.executemany("INSERT INTO threads VALUES (${withName ? '?,?,?,?,?,?,?' : '?,?,?,?,?,?'})",rows)\nc.commit()\nc.close()`;
  const result = spawnSync(python, ['-c', code, join(home, 'state_5.sqlite')]);
  assert.equal(result.status, 0, result.stderr.toString());
}
for (const withName of [true, false]) {
  test(`Codex read-only SQLite rows match Python (name column=${withName})`, t => {
    const { path, env } = sandbox(t);
    const home = join(path, 'codex #?% home');
    makeDatabase(home, withName);
    const before = readFileSync(join(home, 'state_5.sqlite'));
    for (const all of [[], ['--all']]) {
      const { node, reference } = compare(['list', '--agent', 'codex', '--codex-home', home, ...all], env);
      assert.deepEqual(node.value.discovery, reference.value.discovery);
      assert.equal(node.value.codexHome, reference.value.codexHome);
      assert.equal('alive' in node.value.sessions[0], false);
      assert.equal('reachable' in node.value.sessions[0], false);
    }
    assert.deepEqual(readFileSync(join(home, 'state_5.sqlite')), before);
    assert.deepEqual(readdirSync(home), ['state_5.sqlite']);
  });
}

test('missing, invalid and unsupported databases fail without raw content in errors', t => {
  const { path, env } = sandbox(t);
  const home = join(path, 'codex');
  for (const state of ['missing', 'corrupt', 'directory']) {
    if (state === 'corrupt') { mkdirSync(home); writeFileSync(join(home, 'state_5.sqlite'), 'SECRET-SENTINEL'); }
    if (state === 'directory') { rmSync(join(home, 'state_5.sqlite')); mkdirSync(join(home, 'state_5.sqlite')); }
    const result = compare(['list', '--agent', 'codex', '--codex-home', home], env).node;
    assert.equal(result.status, fixture.exitCodes.error);
    assert.equal(JSON.stringify(result).includes('SECRET-SENTINEL'), false);
  }
});

test('unsupported SQLite schema and row types cannot become partial success', t => {
  const { path, env } = sandbox(t);
  const home = join(path, 'codex');
  makeDatabase(home);
  for (const statement of ["UPDATE threads SET updated_at='SECRET-SENTINEL'", 'DROP TABLE threads']) {
    const changed = spawnSync(python, ['-c',
      'import sqlite3,sys\nc=sqlite3.connect(sys.argv[1]); c.execute(sys.argv[2]); c.commit(); c.close()',
      join(home, 'state_5.sqlite'), statement]);
    assert.equal(changed.status, 0);
    const result = compare(['list', '--agent', 'codex', '--codex-home', home], env).node;
    assert.equal(result.status, 1);
    assert.deepEqual(result.value.sessions, []);
    assert.equal(JSON.stringify(result).includes('SECRET-SENTINEL'), false);
  }
});

test('unsupported commands/transports fail before inspecting state or sending anything', t => {
  const { env } = sandbox(t);
  for (const args of [
    ['send', '--to', 'SECRET-SENTINEL', '--message', 'SECRET-SENTINEL'],
    ['send', '--dry-run'], ['device'], ['doctor'], ['update'], ['reply'],
    ['list', '--agent', 'claude', '--host', 'SECRET-SENTINEL'],
    ['list', '--agent', 'claude', '--device', 'SECRET-SENTINEL'],
    ['list', '--agent', 'antigravity'], ['list'], ['list', '--agent', 'codex'],
    ['list', '--agent', 'claude', '--all=false'], ['list', '--agent', 'claude', '--wake'],
  ]) {
    const result = invoke(process.execPath, [cli, ...args, '--json'], env);
    assert.equal(result.status, fixture.exitCodes.noTargetOrUsage);
    assert.equal(result.value.ok, false);
    assert.equal(result.value.submitted, false);
    assert.equal(result.value.consumptionConfirmed, false);
    assert.equal(JSON.stringify(result).includes('SECRET-SENTINEL'), false);
  }
});

test('runtime works without executables on PATH', t => {
  const { env } = sandbox(t);
  const result = invoke(process.execPath, [cli, 'list', '--agent', 'claude', '--json'], { ...env, PATH: '' });
  assert.equal(result.status, 0);
  assert.deepEqual(result.value.sessions, []);
});
