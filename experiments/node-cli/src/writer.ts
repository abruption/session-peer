import { closeSync, constants, fstatSync, lstatSync, openSync, readdirSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { isAbsolute, join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { canonical, Refusal } from './discovery.js';
import { executable, run } from './process.js';

const missing = (error: unknown) => ['ENOENT', 'ENOTDIR'].includes((error as NodeJS.ErrnoException).code ?? '');
export const uuid = (value: string) => /^[\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12}$/i.test(value);
function snapshot(path: string): string {
  const s = lstatSync(path, { bigint: true });
  return [s.dev, s.ino, s.size, s.mtimeNs].join(':');
}
export async function probeLock(path: string): Promise<'free' | 'held' | 'absent' | 'unknown'> {
  let fd: number | undefined;
  try {
    const before = lstatSync(path);
    if (!before.isFile() || before.isSymbolicLink()) return 'unknown';
    const { flockSync } = await import('fs-ext-extra-prebuilt');
    fd = openSync(path, constants.O_RDWR | constants.O_NOFOLLOW);
    const after = fstatSync(fd);
    if (before.dev !== after.dev || before.ino !== after.ino) return 'unknown';
    try { flockSync(fd, 'exnb'); }
    catch (error) { return ['EAGAIN', 'EACCES', 'EWOULDBLOCK'].includes((error as NodeJS.ErrnoException).code ?? '') ? 'held' : 'unknown'; }
    flockSync(fd, 'un');
    return 'free';
  } catch (error) { return missing(error) ? 'absent' : 'unknown'; }
  finally { if (fd !== undefined) closeSync(fd); }
}
type Owner = { pid: number; uid?: number; command?: string; start?: string };
async function sample(path: string) {
  const state = await probeLock(path);
  if (state !== 'held') return { state, fingerprint: '', owners: [] as Owner[], valid: true };
  const fingerprint = snapshot(path);
  const listed = await run(executable('lsof'), ['-nP', '-F0pcu', '--', path]);
  const owners: Owner[] = [];
  let current: Owner | undefined;
  for (const token of listed.stdout.split(/[\0\n]/)) {
    const value = token.slice(1).trim();
    if (token[0] === 'p') { current = { pid: Number(value) }; owners.push(current); }
    if (current && token[0] === 'u') current.uid = Number(value);
    if (current && token[0] === 'c') current.command = value;
  }
  for (const owner of owners) {
    if (!Number.isSafeInteger(owner.pid) || owner.pid <= 1) continue;
    const result = await run(executable('ps'), ['-p', String(owner.pid), '-o', 'lstart='], { env: { ...process.env, LC_ALL: 'C' } });
    if (result.code === 0 && !result.interrupted) owner.start = result.stdout.trim();
  }
  return { state, fingerprint, owners, valid: listed.code === 0 && !listed.interrupted };
}
export async function inspectWriter(home: string, id: string) {
  const path = join(home, 'thread-writer-locks', `${id}.lock`);
  const before = await sample(path);
  if (before.state === 'free' || before.state === 'absent') return { activity: 'inactive', identity: '' };
  if (before.state !== 'held') throw new Refusal('active_writer_unverified', 1);
  await delay(250);
  const after = await sample(path);
  const owner = after.owners[0];
  if (!before.valid || !after.valid || before.state !== after.state || before.fingerprint !== after.fingerprint ||
      before.owners.length !== 1 || after.owners.length !== 1 || JSON.stringify(before.owners) !== JSON.stringify(after.owners) ||
      !owner?.start || owner.uid !== process.getuid?.() || !/^codex(?:-|$)/i.test(owner.command ?? '')) {
    throw new Refusal('active_writer_unverified', 1);
  }
  return { activity: 'live_writer', identity: JSON.stringify({ fingerprint: after.fingerprint, ...owner }) };
}
export function homes(selected: string): string[] {
  const result = new Set([canonical(selected)]);
  const addExisting = (home: string) => {
    try { if (!statSync(join(home, 'state_5.sqlite')).isFile()) throw new Refusal('home_inventory_unreadable', 1); result.add(canonical(home)); }
    catch (error) { if (!missing(error)) throw new Refusal('home_inventory_unreadable', 1); }
  };
  addExisting(join(homedir(), '.codex'));
  if (process.env.CODEX_HOME) addExisting(process.env.CODEX_HOME);
  if (process.platform === 'darwin') {
    const directory = join(homedir(), 'Library/Application Support/orca/codex-accounts');
    let entries: string[] = [];
    try { entries = readdirSync(directory).sort(); }
    catch (error) { if (!missing(error)) throw new Refusal('home_inventory_unreadable', 1); }
    for (const entry of entries) addExisting(join(directory, entry, 'home'));
  }
  if (process.env.SESSION_PEER_CODEX_HOMES) {
    let paths: unknown;
    try { paths = JSON.parse(process.env.SESSION_PEER_CODEX_HOMES); } catch { throw new Refusal('invalid_home_configuration', 1); }
    if (!Array.isArray(paths) || paths.some(p => typeof p !== 'string' || (!isAbsolute(p) && !p.startsWith('~/')))) throw new Refusal('invalid_home_configuration', 1);
    for (const path of paths) result.add(canonical(path));
  }
  return [...result].sort();
}
export async function resolveWriter(selected: string, id: string): Promise<string> {
  const { DatabaseSync } = await import('node:sqlite');
  const candidates = homes(selected);
  const matches: { home: string; activity: string; identity: string }[] = [];
  for (const home of candidates) {
    let saved = false;
    try {
      const db = new DatabaseSync(join(home, 'state_5.sqlite'), { readOnly: true });
      try { db.exec('PRAGMA query_only=ON; PRAGMA trusted_schema=OFF; PRAGMA busy_timeout=3000'); saved = Boolean(db.prepare('SELECT 1 FROM threads WHERE id=? LIMIT 1').get(id)); }
      finally { db.close(); }
    } catch { throw new Refusal('home_inventory_unreadable', 1); }
    if (saved) matches.push({ home, ...await inspectWriter(home, id) });
  }
  const live = matches.filter(c => c.activity === 'live_writer');
  if (!matches.length) throw new Refusal('thread_not_saved_in_known_homes', 2);
  if (live.length !== 1) throw new Refusal(live.length ? 'multiple_live_writers' : 'inactive_writer', 1);
  if (live[0]!.home !== canonical(selected)) throw new Refusal('explicit_home_conflicts_with_live_writer', 1);
  // Include inactive competitors and inventory in the pre-submit revalidation token.
  return JSON.stringify({ candidates, matches });
}
