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

