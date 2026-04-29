export type Bencodable =
  | number
  | string
  | Uint8Array
  | Bencodable[]
  | { [k: string]: Bencodable };

const enc = new TextEncoder();

function concat(parts: Uint8Array[]): Uint8Array {
  const len = parts.reduce((n, p) => n + p.length, 0);
  const out = new Uint8Array(len);
  let off = 0;
  for (const p of parts) {
    out.set(p, off);
    off += p.length;
  }
  return out;
}

export function bencode(obj: Bencodable): Uint8Array {
  if (typeof obj === "number") {
    if (!Number.isInteger(obj)) throw new TypeError("bencode: non-integer number");
    return enc.encode(`i${obj}e`);
  }
  if (typeof obj === "string") {
    const bytes = enc.encode(obj);
    return concat([enc.encode(`${bytes.length}:`), bytes]);
  }
  if (obj instanceof Uint8Array) {
    return concat([enc.encode(`${obj.length}:`), obj]);
  }
  if (Array.isArray(obj)) {
    return concat([enc.encode("l"), ...obj.map(bencode), enc.encode("e")]);
  }
  if (obj && typeof obj === "object") {
    const keys = Object.keys(obj).sort();
    const parts: Uint8Array[] = [enc.encode("d")];
    for (const k of keys) {
      parts.push(bencode(k), bencode(obj[k]!));
    }
    parts.push(enc.encode("e"));
    return concat(parts);
  }
  throw new TypeError(`Cannot bencode ${typeof obj}`);
}

/**
 * Choose piece size targeting ~1500 pieces, clamped to [256KB, 16MB] (powers of two).
 */
export function computePieceSize(fileSize: number): number {
  if (fileSize <= 0) return 256 * 1024;
  const targetPieces = 1500;
  const raw = Math.floor(fileSize / targetPieces);
  const log = Math.ceil(Math.log2(Math.max(raw, 1)));
  const power = Math.max(18, Math.min(24, log));
  return 1 << power;
}
