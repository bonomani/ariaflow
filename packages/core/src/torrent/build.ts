import { createHash } from "node:crypto";
import { bencode, computePieceSize, type Bencodable } from "./bencode.js";

interface BuiltTorrent {
  torrentBytes: Uint8Array;
  infohash: string;
  pieceCount: number;
  fileSize: number;
}

const sha1 = (data: Uint8Array): Uint8Array =>
  new Uint8Array(createHash("sha1").update(data).digest());

const sha1Hex = (data: Uint8Array): string => createHash("sha1").update(data).digest("hex");

/**
 * Build a private single-file .torrent in memory.
 * Pure: no filesystem access — caller passes raw file bytes.
 */
export function buildPrivateTorrent(opts: {
  name: string;
  fileBytes: Uint8Array;
  trackerUrl: string;
  comment?: string;
  createdBy?: string;
}): BuiltTorrent {
  const { name, fileBytes, trackerUrl, comment, createdBy = "ariaflow-server" } = opts;
  const fileSize = fileBytes.length;
  if (fileSize === 0) throw new Error("Cannot create torrent from empty file");

  const pieceSize = computePieceSize(fileSize);
  const pieceCount = Math.ceil(fileSize / pieceSize);
  const pieces = new Uint8Array(pieceCount * 20);
  for (let i = 0; i < pieceCount; i++) {
    const chunk = fileBytes.subarray(i * pieceSize, Math.min((i + 1) * pieceSize, fileSize));
    pieces.set(sha1(chunk), i * 20);
  }

  const info: Record<string, Bencodable> = {
    length: fileSize,
    name,
    "piece length": pieceSize,
    pieces,
    private: 1,
  };
  const infoBencoded = bencode(info);
  const infohash = sha1Hex(infoBencoded);

  const torrent: Record<string, Bencodable> = {
    announce: trackerUrl,
    "created by": createdBy,
    info,
  };
  if (comment) torrent.comment = comment;

  return { torrentBytes: bencode(torrent), infohash, pieceCount, fileSize };
}

/**
 * Extract the infohash (SHA1 of bencoded info dict) from raw .torrent bytes
 * by locating `4:infod...e` and walking the bencode structure.
 */
export function extractInfohash(torrentBytes: Uint8Array): string {
  const marker = new TextEncoder().encode("4:infod");
  const idx = indexOf(torrentBytes, marker);
  if (idx < 0) throw new Error("Cannot find info dict in torrent");
  const infoStart = idx + 6; // skip "4:info", keep leading 'd'

  let depth = 0;
  let i = infoStart;
  while (i < torrentBytes.length) {
    const c = torrentBytes[i]!;
    if (c === 0x64 /* d */ || c === 0x6c /* l */) {
      depth += 1;
      i += 1;
    } else if (c === 0x65 /* e */) {
      depth -= 1;
      if (depth === 0) {
        return sha1Hex(torrentBytes.subarray(infoStart, i + 1));
      }
      i += 1;
    } else if (c === 0x69 /* i */) {
      const end = torrentBytes.indexOf(0x65, i);
      if (end < 0) throw new Error("Malformed bencode integer");
      i = end + 1;
    } else if (c >= 0x30 && c <= 0x39 /* 0-9 */) {
      const colon = torrentBytes.indexOf(0x3a, i);
      if (colon < 0) throw new Error("Malformed bencode string");
      const len = Number(new TextDecoder().decode(torrentBytes.subarray(i, colon)));
      i = colon + 1 + len;
    } else {
      i += 1;
    }
  }
  throw new Error("Malformed torrent: info dict not closed");
}

function indexOf(haystack: Uint8Array, needle: Uint8Array): number {
  outer: for (let i = 0; i <= haystack.length - needle.length; i++) {
    for (let j = 0; j < needle.length; j++) {
      if (haystack[i + j] !== needle[j]) continue outer;
    }
    return i;
  }
  return -1;
}
