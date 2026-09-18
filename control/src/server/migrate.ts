import { getMigrations } from "better-auth/db/migration";
import { createAuth } from "./auth.js";
import { loadConfig } from "./config.js";
import { openDatabase } from "./storage.js";
process.umask(0o077);
const config = loadConfig();
const db = openDatabase(config.dataDir);
try {
  const auth = createAuth(db, config);
  const migrations = await getMigrations(auth.options);
  await migrations.runMigrations();
  console.log("Auth schema migrated.");
} finally {
  db.close();
}
