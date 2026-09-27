import { spawn } from 'node:child_process';
import { accessSync, constants, realpathSync, statSync } from 'node:fs';
import { delimiter, isAbsolute, join } from 'node:path';
import { Refusal } from './discovery.js';

export class UnknownOutcome extends Error {}
export function executable(name: string): string {
  const paths = isAbsolute(name) ? [name] : name.includes('/') ? [] :
    (process.env.PATH ?? '').split(delimiter).filter(Boolean).map(p => join(p, name));
  for (const path of paths) {
    try { accessSync(path, constants.X_OK); if (statSync(path).isFile()) return realpathSync(path); } catch {}
  }
  throw new Refusal('executable_unavailable', 1);
}
export type Done = { code: number | null; stdout: string; spawned: boolean; interrupted: boolean };
export function run(binary: string, args: string[], options: {
  env?: NodeJS.ProcessEnv; input?: string; timeout?: number; limit?: number;
} = {}): Promise<Done> {
  return new Promise(resolve => {
    let stdout = '', bytes = 0, spawned = false, interrupted = false;
    const child = spawn(binary, args, { shell: false, env: options.env ?? process.env, stdio: ['pipe', 'pipe', 'pipe'] });
    const stop = () => { interrupted = true; child.kill('SIGKILL'); };
    const timer = setTimeout(stop, options.timeout ?? 3000);
    child.once('spawn', () => { spawned = true; });
    child.stdin.on('error', () => { /* Close/exit determines outcome, never resend. */ });
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', (part: string) => {
      bytes += Buffer.byteLength(part);
      if (bytes > (options.limit ?? 1024 * 1024)) stop();
      else stdout += part;
    });
    // Drain but never report native stderr (it may contain message text/credentials).
    child.stderr.on('data', (part: Buffer) => { bytes += part.length; if (bytes > (options.limit ?? 1024 * 1024)) stop(); });
    child.once('error', () => { interrupted = true; });
    child.once('close', code => { clearTimeout(timer); resolve({ code, stdout, spawned, interrupted }); });
    child.stdin.end(options.input);
  });
}
