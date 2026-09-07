// Test-only Node IO guard; not product isolation or a substitute for native hooks.
import fs from "node:fs";
import path from "node:path";
import net from "node:net";
import { fileURLToPath } from "node:url";
import { syncBuiltinESMExports } from "node:module";

const root = path.resolve(process.env.SIQ_FIXTURE_ROOT);
const endpoints = new Set(JSON.parse(process.env.SIQ_FIXTURE_ENDPOINTS));
const realpath = fs.realpathSync.bind(fs);
function inside(candidate) { return candidate === root || candidate.startsWith(root + path.sep); }
function checked(value, writing = false) {
  if (typeof value === "number") return;
  if (value instanceof URL) value = fileURLToPath(value);
  const lexical = path.resolve(Buffer.isBuffer(value) ? value.toString() : String(value));
  let resolved = lexical;
  try { resolved = realpath(lexical); } catch {
    try { resolved = path.join(realpath(path.dirname(lexical)), path.basename(lexical)); } catch {}
  }
  if (inside(lexical) && inside(resolved)) return;
  const privatePath = /\/(?:\.codebuddy|\.hermes|\.openclaw|\.codex|\.ssh|\.aws|\.config)(?:\/|$)/;
  const privateName = /^(?:\.env(?:\..*)?|\.netrc|\.git-credentials|auth\.json|credentials\.json)$/;
  if (writing || privatePath.test(lexical) || privatePath.test(resolved) || privateName.test(path.basename(resolved))) {
    const error = new Error("fixture rejects non-fixture file access");
    error.code = "EACCES";
    throw error;
  }
}
for (const [names, writing] of [
  [["readFile", "readFileSync", "readdir", "readdirSync"], false],
  [["writeFile", "writeFileSync", "appendFile", "appendFileSync", "mkdir", "mkdirSync", "unlink", "unlinkSync", "rm", "rmSync"], true],
]) {
  for (const name of names) {
    const original = fs[name].bind(fs);
    fs[name] = (file, ...rest) => { checked(file, writing); return original(file, ...rest); };
    if (!name.endsWith("Sync") && typeof fs.promises[name] === "function") {
      const promiseOriginal = fs.promises[name].bind(fs.promises);
      fs.promises[name] = async (file, ...rest) => { checked(file, writing); return promiseOriginal(file, ...rest); };
    }
  }
}
for (const name of ["rename", "renameSync", "copyFile", "copyFileSync"]) {
  const original = fs[name].bind(fs);
  fs[name] = (from, to, ...rest) => { checked(from, name.startsWith("rename")); checked(to, true); return original(from, to, ...rest); };
  if (!name.endsWith("Sync")) {
    const promiseOriginal = fs.promises[name].bind(fs.promises);
    fs.promises[name] = async (from, to, ...rest) => { checked(from, name.startsWith("rename")); checked(to, true); return promiseOriginal(from, to, ...rest); };
  }
}
function opensForWrite(flags) {
  return typeof flags === "number"
    ? !!(flags & (fs.constants.O_WRONLY | fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_TRUNC | fs.constants.O_APPEND))
    : /[wa+]/.test(String(flags ?? "r"));
}
for (const name of ["open", "openSync"]) {
  const original = fs[name].bind(fs);
  fs[name] = (file, flags, ...rest) => { checked(file, opensForWrite(flags)); return original(file, flags, ...rest); };
}
const openPromise = fs.promises.open.bind(fs.promises);
fs.promises.open = async (file, flags, ...rest) => { checked(file, opensForWrite(flags)); return openPromise(file, flags, ...rest); };
for (const [name, writing] of [["createReadStream", false], ["createWriteStream", true]]) {
  const original = fs[name].bind(fs);
  fs[name] = (file, ...rest) => { checked(file, writing); return original(file, ...rest); };
}
const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) {
  let options = args[0];
  if (Array.isArray(options)) options = options[0];
  if (typeof options !== "object" || options === null) options = { port: args[0], host: typeof args[1] === "string" ? args[1] : "localhost" };
  if (options.path || !endpoints.has(`${options.host ?? "localhost"}:${options.port}`)) throw new Error("fixture rejects non-fixture connection");
  return Reflect.apply(connect, this, args);
};
syncBuiltinESMExports();
