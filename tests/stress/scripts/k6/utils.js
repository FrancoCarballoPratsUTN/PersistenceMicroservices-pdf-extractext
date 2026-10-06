import http from "k6/http";
import { check } from "k6";
import { randomBytes, sha256 } from "k6/crypto";

export const BASE_URL = __ENV.BASE_URL || "http://localhost:8082";

const TOKEN = __ENV.SERVICE_API_TOKEN || "";
if (!TOKEN) {
  throw new Error(
    "SERVICE_API_TOKEN no definida: pasa --env SERVICE_API_TOKEN=... o exportala antes de correr k6.",
  );
}

const AUTH = { Authorization: `Bearer ${TOKEN}` };
const JSON_HEADERS = { ...AUTH, "Content-Type": "application/json" };

export function uniqueChecksum() {
  return sha256(randomBytes(16), "hex");
}

export function crudCycle() {
  const checksum = uniqueChecksum();
  const itemUrl = `${BASE_URL}/texts?checksum=${checksum}`;

  const created = http.post(
    `${BASE_URL}/texts`,
    JSON.stringify({ checksum, text: `k6 stress ${checksum}` }),
    { headers: JSON_HEADERS },
  );
  check(created, { "POST crea (201)": (r) => r.status === 201 });

  const fetched = http.get(itemUrl, { headers: AUTH });
  check(fetched, { "GET lee (200)": (r) => r.status === 200 });

  const updated = http.put(
    itemUrl,
    JSON.stringify({ name: `stress-${checksum}` }),
    { headers: JSON_HEADERS },
  );
  check(updated, { "PUT actualiza (200)": (r) => r.status === 200 });

  const deleted = http.del(itemUrl, null, { headers: AUTH });
  check(deleted, { "DELETE borra (200)": (r) => r.status === 200 });
}
