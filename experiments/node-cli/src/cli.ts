#!/usr/bin/env node
import { hostname } from 'node:os';
import { claude, codex, Refusal } from './discovery.js';
import { executable, run, UnknownOutcome } from './process.js';
import { checkMessage, send } from './send.js';
import { envelope, host, reply, VERSION } from './protocol.js';

type Options = { command: 'list' | 'send'; values: Map<string, string>; flags: Set<string> };
export function parse(args: string[]): Options {
  const command = args[0];
  if (command !== 'list' && command !== 'send') throw new Refusal('unsupported_command');
  const values = new Map<string, string>(), flags = new Set<string>();
  for (let i = 1; i < args.length; i++) {
    const token = args[i]!;
    const split = token.indexOf('=');
    const key = split > 0 ? token.slice(0, split) : token;
    if (['--json', '--all', '--dry-run', '--no-from', '--no-reply-to', '--no-update-notice'].includes(key)) {
      if (flags.has(key) || split > 0) throw new Refusal('invalid_option');
      flags.add(key);
    } else if (['--agent', '--codex-home', '--codex-bin', '--output-format', '--to', '--message', '-m', '--host', '--remote-bin', '--reply-address'].includes(key)) {
      const name = key === '-m' ? '--message' : key;
      const value = split > 0 ? token.slice(split + 1) : args[++i];
      if (value === undefined || values.has(name)) throw new Refusal('invalid_option');
      values.set(name, value);
    } else throw new Refusal('unsupported_option');
  }
  if (!flags.has('--json') && values.get('--output-format') !== 'json') throw new Refusal('json_output_required');
  if (values.has('--output-format') && values.get('--output-format') !== 'json') throw new Refusal('unsupported_output_format');
  if (command === 'list') {
    if (!['claude', 'codex'].includes(values.get('--agent') ?? '')) throw new Refusal('explicit_supported_agent_required');
    if (values.get('--agent') === 'codex' && !values.get('--codex-home')) throw new Refusal('explicit_codex_home_required');
    if (values.get('--agent') !== 'codex' && values.has('--codex-home')) throw new Refusal('inapplicable_option');
    if (['--to', '--message', '--codex-bin', '--reply-address'].some(k => values.has(k)) || ['--dry-run', '--no-from', '--no-reply-to'].some(k => flags.has(k))) throw new Refusal('inapplicable_option');
  } else {
    if (!values.get('--to') || values.has('--agent') || flags.has('--all')) throw new Refusal('invalid_send_options');
    if (flags.has('--no-reply-to') && values.has('--reply-address')) throw new Refusal('conflicting_reply_options');
    if (values.get('--to')!.startsWith('session-peer:')) {
      const route = reply(values.get('--to')!);
      for (const [key, value] of [['--host', route.host], ['--codex-home', route.home]] as const) {
        if (values.has(key) && values.get(key) !== value) throw new Refusal('reply_route_conflict');
        if (value !== undefined) values.set(key, value);
      }
      values.set('--to', route.to);
    }
  }
  if (values.has('--host')) host(values.get('--host')!);
  if (values.has('--remote-bin')) {
    if (!values.has('--host') || !/^\/[\x20-\x7e]+$/.test(values.get('--remote-bin')!)) throw new Refusal('invalid_remote_bin');
  }
  return { command, values, flags };
}
async function input(): Promise<string> {
  const chunks: Buffer[] = [];
  let bytes = 0;
  for await (const chunk of process.stdin) {
    const part = Buffer.from(chunk); bytes += part.length;
    if (bytes > 4_100_000) throw new Refusal('input_too_large');
    chunks.push(part);
  }
  try { return new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks)); }
  catch { throw new Refusal('invalid_utf8'); }
}
const quote = (s: string) => "'" + s.replace(/'/g, "'\\''") + "'";
async function remote(options: Options, message?: string): Promise<Record<string, unknown>> {
  const { values, flags, command } = options;
  const target = host(values.get('--host')!);
  const binary = values.get('--remote-bin') ?? 'session-peer-ts';
  const ssh = executable('ssh');
  const base = ['-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10', '--', target];
  const preflight = await run(ssh, [...base, `${quote(binary)} --version`], { timeout: 15000 });
  if (preflight.interrupted || preflight.code !== 0 || preflight.stdout.trim() !== `session-peer-ts ${VERSION}`) throw new Refusal('remote_version_unverified', 1);
  const args = [command, '--json'];
  for (const [key, value] of values) if (['--agent', '--codex-home', '--codex-bin', '--to'].includes(key)) args.push(key, value);
  if (flags.has('--all')) args.push('--all');
  if (flags.has('--dry-run')) args.push('--dry-run');
  if (command === 'send') args.push('--message', message!, '--no-from', '--no-reply-to');
  const done = await run(ssh, [...base, `${quote(binary)} --stdio-request`], {
    timeout: 90000, input: JSON.stringify({ schemaVersion: 1, args })
  });
  const uncertain = () => { if (command === 'send' && !flags.has('--dry-run') && done.spawned) throw new UnknownOutcome(); throw new Refusal('remote_response_unverified', 1); };
  if (done.interrupted || !done.spawned) return uncertain();
  let value: Record<string, unknown>;
  try { value = JSON.parse(done.stdout); } catch { return uncertain(); }
  if (!value || value.schemaVersion !== 1 || value.command !== command || typeof value.ok !== 'boolean' || typeof value.host !== 'string' ||
      ![0, 1, 2].includes(done.code ?? -1) || (value.ok !== (done.code === 0))) return uncertain();
  const expectedStatus = flags.has('--dry-run') ? 'validated' : values.get('--to')?.startsWith('codex:') ? 'queued' : 'posted';
  if (command === 'send' && (value.consumptionConfirmed !== false ||
      (value.ok && (value.submitted !== !flags.has('--dry-run') || value.status !== expectedStatus)) ||
      (!value.ok && !((value.submitted === false && value.status === 'refused') || (value.submitted === null && value.status === 'unknown'))))) return uncertain();
  return { ...value, host: target, sshHost: target };
}

let command = 'unknown';
try {
  const [major, minor] = process.versions.node.split('.').map(Number);
  if (!((major === 22 && minor! >= 13) || major === 24)) throw new Refusal('unsupported_node_version');
  if (!['darwin', 'linux'].includes(process.platform)) throw new Refusal('unsupported_platform');
  let args = process.argv.slice(2);
  if (args.length === 1 && args[0] === '--version') console.log(`session-peer-ts ${VERSION}`);
  else if (args.length === 1 && ['--help', '-h'].includes(args[0]!)) console.log('session-peer-ts preview: list --agent claude|codex --json; send --to TARGET --message TEXT --json [--dry-run] [--host HOST] [--remote-bin ABSOLUTE_PATH]. Codex requires --codex-home. Relay/MCP/wake/Windows unsupported.');
  else {
    const wire = args.length === 1 && args[0] === '--stdio-request';
    if (wire) {
      let request: unknown;
      try { request = JSON.parse(await input()); } catch { throw new Refusal('invalid_remote_request'); }
      const record = request as { schemaVersion?: unknown; args?: unknown };
      if (!record || record.schemaVersion !== 1 || !Array.isArray(record.args) || record.args.some(a => typeof a !== 'string')) throw new Refusal('invalid_remote_request');
      args = record.args;
    }
    command = ['list', 'send'].includes(args[0] ?? '') ? args[0]! : 'unknown';
    const options = parse(args);
    if (wire && (options.values.has('--host') || options.values.has('--remote-bin'))) throw new Refusal('nested_transport_forbidden');
    let message: string | undefined;
    if (command === 'send') {
      message = options.values.get('--message');
      if (message === undefined || message === '-') { if (wire) throw new Refusal('remote_message_required'); message = await input(); }
      message = envelope(message, options.flags.has('--no-from'), options.values.get('--reply-address'));
      checkMessage(message, options.values.get('--to')!.startsWith('codex:'));
    }
    let result: Record<string, unknown>;
    if (options.values.has('--host')) result = await remote(options, message);
    else if (command === 'send') result = await send({ to: options.values.get('--to')!, home: options.values.get('--codex-home'), codexBin: options.values.get('--codex-bin'), message: message!, dryRun: options.flags.has('--dry-run') });
    else result = options.values.get('--agent') === 'claude' ? claude(options.flags.has('--all')) : await codex(options.values.get('--codex-home')!, options.flags.has('--all'));
    console.log(JSON.stringify({ schemaVersion: 1, host: hostname(), command, ok: result.ok !== false, version: VERSION, referenceVersion: '1.0.2', ...result }));
    process.exitCode = result.ok === false ? 1 : 0;
  }
} catch (error) {
  const unknown = error instanceof UnknownOutcome;
  const failure = error instanceof Refusal ? error : new Refusal('operation_failed', 1);
  console.log(JSON.stringify({ schemaVersion: 1, host: hostname(), command, ok: false,
    error: unknown ? 'outcome_unknown' : failure.code, status: unknown ? 'unknown' : 'refused',
    submitted: unknown ? null : false, consumptionConfirmed: false, retryAllowed: false }));
  process.exitCode = unknown ? 1 : failure.exitCode;
}
