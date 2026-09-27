// Deliberately read-only: no subprocess, network, socket connection or DB writes.
import { readFileSync, readdirSync, realpathSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';

type Row = Record<string, unknown>;
export class Refusal extends Error {
  constructor(readonly code: string, readonly exitCode = 2) { super(code); }
}

function missing(error: unknown): boolean {
  return ['ENOENT', 'ENOTDIR'].includes((error as NodeJS.ErrnoException).code ?? '');
}
export function canonical(path: string): string {
  if (path === '~' || path.startsWith('~/')) path = join(homedir(), path.slice(2));
  else if (path.startsWith('~')) throw new Refusal('unsupported_home_expansion');
  const absolute = resolve(path);
  try { return realpathSync(absolute); }
  catch (error) {
    if (!missing(error)) throw new Refusal('home_resolution_failed', 1);
    const parent = dirname(absolute);
    return parent === absolute ? absolute : join(canonical(parent), absolute.slice(parent.length));
  }
}
function alive(pid: number): boolean {
  if (pid <= 1) return false;
  try { process.kill(pid, 0); return true; }
  catch (error) { return (error as NodeJS.ErrnoException).code === 'EPERM'; }
}
export function claude(all: boolean): Row {
  const directory = join(process.env.CLAUDE_CONFIG_DIR || process.env.ANTHROPIC_CONFIG_DIR || join(homedir(), '.claude'), 'sessions');
  let entries: string[];
  try { entries = readdirSync(directory).sort(); }
  catch (error) {
    if (missing(error)) entries = [];
    else throw new Refusal('claude_discovery_failed', 1);
  }
  const sessions: Row[] = [];
  for (const entry of entries) {
    if (!/^[0-9]+\.json$/.test(entry)) continue;
    let record: Row;
    try {
      const value: unknown = JSON.parse(readFileSync(join(directory, entry), 'utf8'));
      if (!value || typeof value !== 'object' || Array.isArray(value)) continue;
      record = value as Row;
    } catch { continue; }
    const pid = record.pid;
    if (typeof pid !== 'number' || !Number.isSafeInteger(pid) || pid > 2147483647) continue;
    const matches = pid === Number(entry.slice(0, -5));
    const live = matches && alive(pid);
    const socket = typeof record.messagingSocketPath === 'string' ? record.messagingSocketPath : '';
    let inbox = false;
    if (socket) {
      try { inbox = statSync(socket).isSocket(); } catch { /* Inaccessible is not reachable. */ }
    }
    const row: Row = { agent: 'claude', pid, socket, alive: live, reachable: live && inbox };
    for (const key of ['name', 'status', 'cwd', 'kind', 'version', 'tmux']) row[key] = record[key] ?? null;
    if (!matches) row.staleReason = 'record_pid_mismatch';
    if (all || row.reachable) sessions.push(row);
  }
  return { sessions, discovery: { claude: { status: 'ok' } } };
}

export async function codex(path: string, all: boolean): Promise<Row> {
  const home = canonical(path);
  const file = join(home, 'state_5.sqlite');
  const item: Row = { codexHome: home, stateDb: file, sources: ['argument'] };
  let sessions: Row[] = [];
  let code: string | undefined;
  try {
    if (!statSync(file).isFile()) code = 'state_db_not_regular';
  } catch (error) { code = missing(error) ? 'state_db_missing' : 'state_db_read_failed'; }
  if (!code) {
    try {
      // Lazy import: Claude-only commands don't initialize experimental SQLite.
      const { DatabaseSync } = await import('node:sqlite');
      const db = new DatabaseSync(file, { readOnly: true });
      try {
        db.exec('PRAGMA query_only=ON; PRAGMA trusted_schema=OFF; PRAGMA busy_timeout=3000');
        const columns = new Set((db.prepare('PRAGMA table_info(threads)').all() as Row[]).map(row => row.name));
        const required = ['id', 'title', 'cwd', 'updated_at', 'archived', 'rollout_path'];
        if (!required.every(name => columns.has(name))) throw new Error('unsupported_schema');
        const name = columns.has('name') ? "COALESCE(NULLIF(name, ''), NULLIF(title, ''), id)" : "COALESCE(NULLIF(title, ''), id)";
        const rows = db.prepare(`SELECT id, ${name} AS display_name, cwd, updated_at, archived FROM threads ${all ? '' : 'WHERE archived = 0'} ORDER BY updated_at DESC, id ASC`).all() as Row[];
        sessions = rows.map(row => {
          if (typeof row.id !== 'string' || !row.id || typeof row.display_name !== 'string' ||
              typeof row.updated_at !== 'number' || !Number.isSafeInteger(row.updated_at) ||
              typeof row.archived !== 'number' || (row.cwd !== null && typeof row.cwd !== 'string')) {
            throw new Error('unsupported_row');
          }
          // Python slicing counts Unicode code points, not JS UTF-16 units.
          const firstLine = row.display_name.split(/[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/u)[0] ?? '';
          return { agent: 'codex', id: row.id, name: [...firstLine].slice(0, 120).join(''),
            cwd: row.cwd, updatedAt: row.updated_at, archived: Boolean(row.archived),
            codexHome: home, stateDb: file };
        });
      } finally { db.close(); }
    } catch { code = 'state_db_read_failed'; sessions = []; }
  }
  const failed = Boolean(code);
  Object.assign(item, failed ? { status: 'error', code, error: code } : { status: 'ok', sessionCount: sessions.length });
  const discovery: Row = { status: failed ? 'error' : 'ok', homes: [item] };
  if (failed) discovery.error = 'Codex home discovery is incomplete; inspect homes and errors';
  return { sessions, codexHome: home, discovery: { codex: discovery }, ok: !failed,
    ...(failed ? { error: 'Discovery failed for: codex' } : {}) };
}
