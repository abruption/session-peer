import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, delimiter } from 'node:path';
import { createServer } from 'node:net';
import { once } from 'node:events';
import { fileURLToPath } from 'node:url';
import { probeLock, inspectWriter } from '../dist/writer.js';
import { reply, envelope } from '../dist/protocol.js';

const cli = fileURLToPath(new URL('../dist/cli.js', import.meta.url));
const python = process.env.PYTHON ?? 'python3';
const id = '11111111-1111-4111-8111-111111111111';
function setup(t) {
  const path = mkdtempSync(join(process.env.TASK_TEMP ?? tmpdir(), 'codex-send-'));
  mkdirSync(join(path, '.claude/sessions'), { recursive: true });
  const env = { ...process.env, HOME: path, USERPROFILE: path, CLAUDE_CONFIG_DIR: join(path, '.claude'), CODEX_HOME: '', SESSION_PEER_CODEX_HOMES: '', CODEX_THREAD_ID: '', CODEX_SESSION_ID: '' };
  t.after(() => rmSync(path, { recursive: true }));
  return { path, env };
}
async function invoke(args, env) {
  const child = spawn(process.execPath, [cli, ...args, '--json'], { env, stdio: ['ignore', 'pipe', 'pipe'] });
  let stdout = ''; child.stdout.on('data', x => { stdout += x; }); child.stderr.resume();
  const timer = setTimeout(() => child.kill('SIGKILL'), 15000);
  const [code, signal] = await once(child, 'close'); clearTimeout(timer);
  assert.equal(signal, null);
  return { code, ...JSON.parse(stdout) };
}
async function inbox(t, path) {
  const messages = [];
  const socket = join(path, 'sock');
  const server = createServer(s => {
    let data = ''; s.on('data', chunk => { data += chunk; });
    s.on('end', () => { messages.push(JSON.parse(data)); s.end(); });
  });
  server.listen(socket); await once(server, 'listening');
  t.after(() => new Promise(ok => server.close(ok)));
  writeFileSync(join(path, '.claude/sessions', `${process.pid}.json`), JSON.stringify({ pid: process.pid, name: 'fixture', messagingSocketPath: socket }));
  return messages;
}
test('real Unix inbox: dry-run does not write, send writes exactly one framed message', async t => {
  const { path, env } = setup(t), messages = await inbox(t, path);
  const args = ['send', '--to', String(process.pid), '--message', '한글\nsecond', '--no-from', '--no-reply-to'];
  const dry = await invoke([...args, '--dry-run'], env);
  assert.equal(dry.status, 'validated'); assert.equal(dry.submitted, false); assert.equal(messages.length, 0);
  const sent = await invoke(args, env);
  assert.equal(sent.status, 'posted'); assert.equal(sent.consumptionConfirmed, false);
  assert.deepEqual(messages, [{ type: 'user', message: { role: 'user', content: '한글\nsecond' } }]);
});
test('structured replies are inert data and reject conflicting/unsafe fields', () => {
  assert.deepEqual(reply('session-peer://v1/reply?agent=claude&session=worker&transport=local'), { to: 'worker' });
  assert.equal(reply(`session-peer://v1/reply?agent=codex&session=${id}&transport=ssh&host=user%40host&codexHome=%2Ftmp%2Fhome`).host, 'user@host');
  for (const suffix of ['&agent=claude', '&host=bad', '&extra=x', '&codexHome=/tmp', '&x=%ZZ']) {
    assert.throws(() => reply('session-peer://v1/reply?agent=claude&session=worker&transport=local' + suffix));
  }
  assert.throws(() => reply('session-peer://v1/reply?agent=claude&session=x&transport=ssh&host=-oProxyCommand%3Did'));
  assert.equal(envelope('hello', true), 'hello');
});

function database(home) {
  mkdirSync(join(home, 'thread-writer-locks'), { recursive: true });
  const result = spawnSync(python, ['-c',
    'import sqlite3,sys\nc=sqlite3.connect(sys.argv[1]); c.execute("CREATE TABLE threads(id TEXT)"); c.execute("INSERT INTO threads VALUES (?)",(sys.argv[2],)); c.commit(); c.close()',
    join(home, 'state_5.sqlite'), id]);
  assert.equal(result.status, 0, result.stderr.toString());
}
async function holder(t, path, home, name = 'codex-fixture') {
  // Actual OS flock held by a separate native process, not a mocked lock probe.
  const source = join(path, 'holder.c'), binary = join(path, name);
  writeFileSync(source, '#include <sys/file.h>\n#include <fcntl.h>\n#include <unistd.h>\n#include <stdio.h>\nint main(int argc,char**argv){int f=open(argv[1],O_RDWR|O_CREAT,0600); if(f<0||flock(f,LOCK_EX|LOCK_NB))return 1;puts("ready");fflush(stdout); sleep(60);return 0;}\n');
  const built = spawnSync('cc', [source, '-o', binary]);
  assert.equal(built.status, 0, built.stderr.toString());
  const child = spawn(binary, [join(home, 'thread-writer-locks', `${id}.lock`)], { stdio: ['ignore', 'pipe', 'inherit'] });
  t.after(async () => { if (child.exitCode === null && child.signalCode === null) { child.kill('SIGTERM'); await once(child, 'close'); } });
  await once(child.stdout, 'data');
  return child;
}
test('actual kernel lock + owner correlation; symlink and non-Codex owner fail closed', async t => {
  const { path } = setup(t), home = join(path, 'home'); database(home);
  const lock = join(home, 'thread-writer-locks', `${id}.lock`);
  assert.equal(await probeLock(lock), 'absent');
  writeFileSync(lock, ''); assert.equal(await probeLock(lock), 'free');
  symlinkSync(lock, join(path, 'alias')); assert.equal(await probeLock(join(path, 'alias')), 'unknown');
  await holder(t, path, home, 'not-codex');
  assert.equal(await probeLock(lock), 'held');
  await assert.rejects(inspectWriter(home, id), /active_writer_unverified/);
});
test('Codex guarded queue runs once, refuses inactive or competing live writers', async t => {
  const { path, env } = setup(t), home = join(path, 'home'); database(home);
  const queue = join(path, 'queue'), count = join(path, 'count');
  writeFileSync(queue, `#!${process.execPath}\nrequire('node:fs').appendFileSync(${JSON.stringify(count)},'1'); console.log('queued');`, { mode: 0o700 });
  const args = ['send', '--to', `codex:${id}`, '--codex-home', home, '--codex-bin', queue, '--message', 'fixture', '--no-from'];
  assert.equal((await invoke(args, env)).error, 'inactive_writer');
  await holder(t, path, home);
  const dry = await invoke([...args, '--dry-run'], env); assert.equal(dry.status, 'validated', JSON.stringify(dry));
  const sent = await invoke(args, env); assert.equal(sent.status, 'queued', JSON.stringify(sent));
  assert.equal(readFileSync(count, 'utf8'), '1'); assert.equal(sent.consumptionConfirmed, false);
  const second = join(path, 'second'); database(second);
  await holder(t, path, second, 'codex-second');
  const ambiguous = await invoke(args, { ...env, SESSION_PEER_CODEX_HOMES: JSON.stringify([second]) });
  assert.equal(ambiguous.error, 'multiple_live_writers'); assert.equal(readFileSync(count, 'utf8'), '1');
});
test('queue failure after spawn is unknown, never retried or leaked', async t => {
  const { path, env } = setup(t), home = join(path, 'home'); database(home); await holder(t, path, home);
  const queue = join(path, 'queue'), count = join(path, 'count');
  writeFileSync(queue, `#!${process.execPath}\nrequire('node:fs').appendFileSync(${JSON.stringify(count)},'1'); console.error('SECRET-SENTINEL');process.exit(1);`, { mode: 0o700 });
  const result = await invoke(['send', '--to', `codex:${id}`, '--codex-home', home, '--codex-bin', queue, '--message', 'SECRET-SENTINEL'], env);
  assert.equal(result.status, 'unknown'); assert.equal(result.submitted, null); assert.equal(result.retryAllowed, false);
  assert.equal(JSON.stringify(result).includes('SECRET-SENTINEL'), false); assert.equal(readFileSync(count, 'utf8'), '1');
});
test('SSH request framing: no message in remote command; response loss never retries', async t => {
  const { path, env } = setup(t), messages = await inbox(t, path);
  const ssh = join(path, 'ssh');
  writeFileSync(ssh, `#!${process.execPath}\nconst {spawnSync}=require('node:child_process'); const a=process.argv.slice(2);if(a.at(-1).endsWith('--version')){console.log('session-peer-ts 0.1.0-preview.0');process.exit(0);}if(a.at(-1).includes('SECRET-SENTINEL'))process.exit(99);const input=require('node:fs').readFileSync(0,'utf8');const r=spawnSync(${JSON.stringify(process.execPath)},[${JSON.stringify(cli)},'--stdio-request'],{input,encoding:'utf8',env:process.env});process.stdout.write(r.stdout);process.exit(r.status);`, { mode: 0o700 });
  const result = await invoke(['send', '--host', 'fixture', '--to', String(process.pid), '--message', 'SECRET-SENTINEL', '--no-from'], { ...env, PATH: path + delimiter + env.PATH });
  assert.equal(result.status, 'posted'); assert.equal(messages.length, 1);
  writeFileSync(ssh, `#!${process.execPath}\nif(process.argv.at(-1).endsWith('--version'))console.log('session-peer-ts 0.1.0-preview.0');else process.exit(255);`, { mode: 0o700 });
  const lost = await invoke(['send', '--host', 'fixture', '--to', 'fixture', '--message', 'lost'], { ...env, PATH: path + delimiter + env.PATH });
  assert.equal(lost.status, 'unknown'); assert.equal(lost.retryAllowed, false); assert.equal(messages.length, 1);
});
