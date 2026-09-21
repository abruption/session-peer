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
import { runFirstPartyMigrations, validateFirstPartySchema } from '../../control/dist/server/migrations.js';
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
if (process.env.SESSION_PEER_CONTROL_ALPHA_FIXTURE === '1') {
  db.exec(`
    CREATE TABLE relay_public_signups (providerId TEXT NOT NULL,accountId TEXT NOT NULL,status TEXT NOT NULL,expiresAt INTEGER NOT NULL,createdAt INTEGER NOT NULL,PRIMARY KEY(providerId,accountId));
    CREATE TABLE relay_device_claims (id TEXT PRIMARY KEY,userId TEXT NOT NULL,sessionId TEXT NOT NULL,expiresAt INTEGER NOT NULL);
    CREATE TABLE relay_devices (principal TEXT PRIMARY KEY,userId TEXT NOT NULL,keyFingerprint TEXT NOT NULL,certificateFingerprint TEXT NOT NULL,certificatePEM TEXT NOT NULL,keyGeneration INTEGER NOT NULL,name TEXT NOT NULL,revoked INTEGER NOT NULL DEFAULT 0);
    CREATE INDEX relay_devices_owner ON relay_devices(userId);
    CREATE TABLE relay_challenges (id TEXT PRIMARY KEY,userId TEXT NOT NULL,operation TEXT NOT NULL,payload TEXT NOT NULL,message TEXT NOT NULL,expiresAt INTEGER NOT NULL);
    CREATE INDEX relay_challenge_expiry ON relay_challenges(expiresAt);
    CREATE TABLE relay_operations (operationId TEXT PRIMARY KEY,userId TEXT NOT NULL,requestHash TEXT NOT NULL,result TEXT);
    CREATE INDEX relay_operations_owner ON relay_operations(userId);
    CREATE TABLE relay_contract_metadata (name TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE relay_public_revision (id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL);
    INSERT INTO relay_contract_metadata VALUES('registration','zero_based_v1');
    INSERT INTO relay_public_revision VALUES(1,41);
    INSERT INTO relay_devices VALUES('${'a'.repeat(64)}','alpha-user','${'b'.repeat(64)}','${'b'.repeat(64)}','fixture',2,'retained tombstone',1);
    INSERT INTO relay_operations VALUES('00000000-0000-4000-8000-000000000115','alpha-user','fixture-hash','{"committed":true}');
  `);
  await context.internalAdapter.createUser({
    id: 'alpha-user', name: 'Alpha', email: 'alpha@example.invalid', emailVerified: true,
  }, { method: 'admin' });
}
runFirstPartyMigrations(db);
validateFirstPartySchema(db);
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
  ...(process.env.SESSION_PEER_CONTROL_ALPHA_FIXTURE === '1' ? {
    migrationPreserved: {
      user: db.prepare("SELECT id,email FROM user WHERE id='alpha-user'").get(),
      device: db.prepare("SELECT principal,keyGeneration,revoked FROM relay_devices WHERE userId='alpha-user'").get(),
      operation: db.prepare("SELECT operationId,result FROM relay_operations WHERE userId='alpha-user'").get(),
      revision: db.prepare("SELECT revision FROM relay_public_revision WHERE id=1").get().revision,
      schema: db.prepare("SELECT version FROM session_peer_migrations").get().version,
    },
  } : {}),
}), { mode: 0o600 });
function stop() { server.close(() => { db.close(); process.exit(0); }); }
process.on('SIGTERM', stop);
process.on('SIGINT', stop);
