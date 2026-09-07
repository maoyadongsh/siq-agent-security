// Test-only IO boundary, loaded before the unmodified OpenClaw CLI.
// This is not product isolation and does not replace any platform hooks.
import net from "node:net";
const endpoints = new Set(JSON.parse(process.env.SIQ_FIXTURE_ENDPOINTS));
const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) {
  let options = args[0];
  if (Array.isArray(options)) options = options[0];
  if (typeof options !== "object" || options === null) {
    options = { port: args[0], host: typeof args[1] === "string" ? args[1] : "localhost" };
  }
  const host = options.host ?? "localhost";
  if (options.path || !endpoints.has(`${host}:${options.port}`)) {
    throw new Error("fixture rejects non-fixture connection");
  }
  return Reflect.apply(connect, this, args);
};
