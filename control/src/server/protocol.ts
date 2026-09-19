import {
  createHash,
  verify,
  X509Certificate,
  type KeyObject,
} from "node:crypto";
export class ControlError extends Error {
  constructor(
    public code: string,
    public status = 400,
  ) {
    super(code);
  }
}
export function assert(
  condition: unknown,
  code: string,
  status = 400,
): asserts condition {
  if (!condition) throw new ControlError(code, status);
}
export function sha256(data: string | Buffer) {
  return createHash("sha256").update(data).digest("hex");
}
export function canonical(value: unknown): string {
  if (value === null || typeof value === "string" || typeof value === "boolean")
    return JSON.stringify(value);
  if (typeof value === "number" && Number.isSafeInteger(value))
    return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object")
    return (
      "{" +
      Object.keys(value)
        .sort()
        .map(
          (k) =>
            JSON.stringify(k) +
            ":" +
            canonical((value as Record<string, unknown>)[k]),
        )
        .join(",") +
      "}"
    );
  throw new ControlError("invalid_payload");
}
export function object(value: unknown): Record<string, unknown> {
  assert(
    value && typeof value === "object" && !Array.isArray(value),
    "invalid_payload",
  );
  return value as Record<string, unknown>;
}
export function fields(value: Record<string, unknown>, expected: string[]) {
  assert(
    Object.keys(value).every((k) => expected.includes(k)) &&
      expected.every((k) => Object.hasOwn(value, k)),
    "invalid_fields",
  );
}
export function principal(value: unknown): asserts value is string {
  assert(
    typeof value === "string" && /^[a-f0-9]{64}$/.test(value),
    "invalid_principal",
  );
}
export interface Registration {
  principal: string;
  certificatePEM: string;
  keyGeneration: number;
  name: string;
  operationId: string;
  expectedGeneration?: number;
}
export interface Admission {
  role: "client" | "receiver";
  devicePrincipal: string;
  receiverPrincipal: string;
}
export function registration(value: unknown): Registration {
  const o = object(value);
  fields(o, [
    "principal",
    "certificatePEM",
    "keyGeneration",
    "name",
    "operationId",
    ...(Object.hasOwn(o, "expectedGeneration") ? ["expectedGeneration"] : []),
  ]);
  operationId(o.operationId);
  if (Object.hasOwn(o, "expectedGeneration")) assert(
    Number.isSafeInteger(o.expectedGeneration) &&
      (o.expectedGeneration as number) >= 0 &&
      (o.expectedGeneration as number) < 2147483647,
    "invalid_generation",
  );
  principal(o.principal);
  assert(
    typeof o.certificatePEM === "string" && o.certificatePEM.length <= 8192,
    "invalid_certificate",
  );
  assert(
    Number.isSafeInteger(o.keyGeneration) &&
      (o.keyGeneration as number) >= 0 &&
      (o.keyGeneration as number) <= 2147483647,
    "invalid_generation",
  );
  assert(
    typeof o.name === "string" &&
      o.name.trim().length > 0 &&
      o.name.length <= 80 &&
      !/[\x00-\x1f\x7f]/.test(o.name),
    "invalid_device_name",
  );
  return o as unknown as Registration;
}
export function admission(value: unknown): Admission {
  const o = object(value);
  fields(o, ["role", "devicePrincipal", "receiverPrincipal"]);
  principal(o.devicePrincipal);
  principal(o.receiverPrincipal);
  assert(o.role === "client" || o.role === "receiver", "invalid_role");
  assert(
    o.role !== "receiver" || o.devicePrincipal === o.receiverPrincipal,
    "invalid_receiver",
  );
  return o as unknown as Admission;
}
export function operationId(value: unknown): asserts value is string {
  assert(
    typeof value === "string" &&
      /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(
        value,
      ),
    "invalid_operation_id",
  );
}
export function certificate(
  pem: string,
  now = Date.now(),
  requireValidity = true,
): {
  key: KeyObject;
  keyFingerprint: string;
  certificateFingerprint: string;
  jwk: JsonWebKey;
} {
  assert(
    /^\s*-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----\s*$/.test(
      pem,
    ),
    "invalid_certificate",
  );
  let cert: X509Certificate;
  try {
    cert = new X509Certificate(pem);
  } catch {
    throw new ControlError("invalid_certificate");
  }
  assert(
    cert.publicKey.asymmetricKeyType === "ec" &&
      cert.publicKey.asymmetricKeyDetails?.namedCurve === "prime256v1",
    "invalid_key_type",
  );
  assert(
    !requireValidity ||
      (Date.parse(cert.validFrom) <= now &&
        Date.parse(cert.validTo) > now + 60000),
    "certificate_expired_or_not_valid",
  );
  return {
    key: cert.publicKey,
    keyFingerprint: sha256(cert.raw),
    certificateFingerprint: sha256(cert.raw),
    jwk: cert.publicKey.export({ format: "jwk" }),
  };
}
export function verifyProof(message: string, proof: unknown, key: KeyObject) {
  assert(
    typeof proof === "string" && /^[A-Za-z0-9_-]{80,144}$/.test(proof),
    "invalid_proof",
  );
  try {
    assert(
      verify(
        "sha256",
        Buffer.from(message, "utf8"),
        { key, dsaEncoding: "der" },
        Buffer.from(proof, "base64url"),
      ),
      "invalid_proof",
    );
  } catch {
    throw new ControlError("invalid_proof");
  }
}
export function room(userId: string, receiver: string) {
  return sha256(userId + "\0" + receiver);
}
