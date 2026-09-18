import Database from "better-sqlite3";
import { mkdirSync, chmodSync, lstatSync } from "node:fs";
import { resolve, join } from "node:path";
export function privateDirectory(path: string) {
  const absolute = resolve(path);
  mkdirSync(absolute, { recursive: true, mode: 0o700 });
  const st = lstatSync(absolute);
  if (
    !st.isDirectory() ||
    st.isSymbolicLink() ||
    st.uid !== process.getuid?.() ||
    st.mode & 0o077
  )
    throw new Error("unsafe_private_directory");
  return absolute;
}
export function openDatabase(dataDir: string) {
  const dir = privateDirectory(dataDir);
  const path = join(dir, "control.sqlite");
  try {
    const st = lstatSync(path);
    if (
      !st.isFile() ||
      st.isSymbolicLink() ||
      st.uid !== process.getuid?.() ||
      st.mode & 0o077
    )
      throw new Error("unsafe_database");
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code !== "ENOENT") throw e;
  }
  const db = new Database(path);
  chmodSync(path, 0o600);
  db.pragma("journal_mode = WAL");
  db.pragma("foreign_keys = ON");
  db.pragma("busy_timeout = 3000");
  return db;
}
