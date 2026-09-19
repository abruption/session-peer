// Test-only HTTP bridge around the real Better Auth application. Never deployed.
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';
import { writeFileSync } from 'node:fs';
import { openDatabase } from '../../control/dist/server/storage.js';
import { createAuth } from '../../control/dist/server/auth.js';
import { RelayControl } from '../../control/dist/server/relay-control.js';
import { createApp } from '../../control/dist/server/app.js';
const require = createRequire(new URL('../../control/package.json', import.meta.url));
const { getMigrations } = await import(pathToFileURL(require.resolve('better-auth/db/migration')));
process.umask(0o077);
const root = process.argv[2];
const config = {
  origin: 'https://relay.example.test', production: true,
  secret: 'cross-language-test-only-not-a-production-secret',
  dataDir: join(root, 'private'), publicDir: join(root, 'relay-public'),
  providers: {}, allowlist: [{ provider: 'github', accountId: 'fixture-one' },
                            { provider: 'google', accountId: 'fixture-two' }],
};
const db = openDatabase(config.dataDir);
const auth = createAuth(db, config);
await (await getMigrations(auth.options)).runMigrations();
const context = await auth.$context;
const accounts = [];
for (const [i, allowed] of config.allowlist.entries()) {
  const user = await context.internalAdapter.createUser({
    name: 'Test', email: `test-${i}@example.invalid`, emailVerified: true,
  }, { method: 'admin' });
  await context.internalAdapter.createAccount({ userId: user.id,
    providerId: allowed.provider, accountId: allowed.accountId });
  const session = await context.internalAdapter.createSession(user.id);
  accounts.push({ userId: user.id, token: session.token });
}
const control = new RelayControl(db, config);
const app = createApp(auth, db, control, config, root);
const server = createServer(async (incoming, outgoing) => {
  try {
    const chunks = [];
    for await (const chunk of incoming) chunks.push(chunk);
    const response = await app(new Request(config.origin + incoming.url, {
      method: incoming.method, headers: incoming.headers,
      body: ['GET', 'HEAD'].includes(incoming.method) ? undefined : Buffer.concat(chunks),
    }));
    outgoing.writeHead(response.status, { 'content-type': 'application/json' });
    outgoing.end(Buffer.from(await response.arrayBuffer()));
  } catch {
    outgoing.writeHead(500); outgoing.end('{"error":"fixture_failure"}');
  }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
writeFileSync(join(root, 'ready.json'), JSON.stringify({
  port: server.address().port, origin: config.origin, accounts,
  stateFile: join(config.publicDir, 'state.json'),
}), { mode: 0o600 });
function stop() { server.close(() => { db.close(); process.exit(0); }); }
process.on('SIGTERM', stop);
process.on('SIGINT', stop);
