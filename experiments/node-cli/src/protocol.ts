import { Refusal } from './discovery.js';
import { uuid } from './writer.js';
export const VERSION = '0.1.0-preview.0';
export function host(value: string): string {
  if (value.length > 255 || !/^(?:[A-Za-z0-9_][A-Za-z0-9_.-]*@)?[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(value)) throw new Refusal('invalid_ssh_host');
  return value;
}
export function reply(value: string): { to: string; host?: string; home?: string } {
  if (value.length > 4096 || /[\x00-\x20\x7f]/.test(value) || /%(?![\da-f]{2})/i.test(value)) throw new Refusal('invalid_reply_uri');
  let url: URL;
  try { url = new URL(value); } catch { throw new Refusal('invalid_reply_uri'); }
  if (url.protocol !== 'session-peer:' || url.host !== 'v1' || url.pathname !== '/reply' || url.hash || url.username || url.password) throw new Refusal('invalid_reply_uri');
  const fields = new Map<string, string>();
  for (const [key, item] of url.searchParams) {
    if (!['agent', 'session', 'transport', 'host', 'codexHome'].includes(key) || fields.has(key) || !item || /[\x00-\x1f\x7f\ufffd]/.test(item)) throw new Refusal('invalid_reply_uri');
    fields.set(key, item);
  }
  const agent = fields.get('agent'), target = fields.get('session'), transport = fields.get('transport');
  if (!target || !['claude', 'codex'].includes(agent ?? '') || !['local', 'ssh'].includes(transport ?? '')) throw new Refusal('invalid_reply_uri');
  if (agent === 'codex' && !uuid(target)) throw new Refusal('invalid_reply_uri');
  if (agent !== 'codex' && fields.has('codexHome')) throw new Refusal('invalid_reply_uri');
  if (transport === 'local' && fields.has('host')) throw new Refusal('invalid_reply_uri');
  if (transport === 'ssh' && !fields.has('host')) throw new Refusal('invalid_reply_uri');
  return { to: agent === 'codex' ? `codex:${target}` : target,
    ...(transport === 'ssh' ? { host: host(fields.get('host')!) } : {}),
    ...(fields.has('codexHome') ? { home: fields.get('codexHome')! } : {}) };
}
export function envelope(text: string, noFrom: boolean, address?: string): string {
  const sender = process.env.CODEX_THREAD_ID || process.env.CODEX_SESSION_ID;
  const from = !noFrom && sender && uuid(sender) ? `From: codex:${sender}\n\n` : '';
  if (address) reply(address);
  // No inferred identity/reverse route and no executable Reply command.
  return from + text.replace(/^\n+|\n+$/g, '') + (address ? `\n\n---\nReply-To: ${address}` : '');
}
