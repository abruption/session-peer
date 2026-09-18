import { loadConfig } from "./config.js";
import { confirmGoogleDiscovery } from "./google-discovery.js";
process.umask(0o077);
try {
  console.log(JSON.stringify(confirmGoogleDiscovery(loadConfig())));
} catch {
  console.error("google_discovery_confirmation_failed");
  process.exitCode = 1;
}
