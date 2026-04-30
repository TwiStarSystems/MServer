"""
Anvil region file (.mca) reader/writer.

Region file structure:
    Bytes 0-4095:    location table — 1024 entries × 4 bytes
                     each = 3-byte big-endian sector offset + 1-byte sector count
    Bytes 4096-8191: timestamp table — 1024 entries × 4 bytes (Unix epoch)
    Bytes 8192+:     chunk data, in 4096-byte sectors
                     each chunk = 4-byte length (big-endian) + 1-byte compression + payload

Chunk indexing in the location table:
    index = (cx & 31) + (cz & 31) * 32

Region file naming: r.<region_x>.<region_z>.mca
    region_x = chunk_x >> 5
    region_z = chunk_z >> 5
"""

import os
import re
import struct
import threading
from pathlib import Path

from . import nbt as nbt_mod

SECTOR_SIZE = 4096
HEADER_SECTORS = 2  # location + timestamp tables

# r.<x>.<z>.mca
_REGION_NAME_RE = re.compile(r'^r\.(-?\d+)\.(-?\d+)\.mca$')


def region_coords_from_filename(filename):
    """Parse region (rx, rz) from 'r.<x>.<z>.mca'. Returns None if invalid."""
    m = _REGION_NAME_RE.match(os.path.basename(filename))
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


def chunk_to_region(cx, cz):
    """Return (region_x, region_z) for a global chunk coord."""
    return (cx >> 5, cz >> 5)


def region_filename(rx, rz):
    return f"r.{rx}.{rz}.mca"


class AnvilRegion:
    """
    Lazy region file reader/writer. Holds an open file handle for the lifetime
    of the object; call close() when done. Thread-safe via internal lock.
    """

    def __init__(self, path, *, create_if_missing=False):
        self.path = Path(path)
        self.rx, self.rz = (None, None)
        coords = region_coords_from_filename(self.path.name)
        if coords:
            self.rx, self.rz = coords

        self._lock = threading.RLock()
        self._fh = None
        # location_table[i] = (sector_offset, sector_count); 0,0 = empty
        self._locations = [(0, 0)] * 1024
        self._timestamps = [0] * 1024
        # Track which sectors are in use (for write allocation)
        self._sectors_used = set()
        self._sectors_used.add(0)
        self._sectors_used.add(1)

        if not self.path.exists():
            if not create_if_missing:
                raise FileNotFoundError(f"Region file not found: {self.path}")
            self._create_empty()
        else:
            self._open_existing()

    def _create_empty(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, 'wb') as f:
            f.write(b'\x00' * (SECTOR_SIZE * HEADER_SECTORS))
        self._fh = open(self.path, 'r+b')

    def _open_existing(self):
        self._fh = open(self.path, 'r+b')
        self._fh.seek(0)
        header = self._fh.read(SECTOR_SIZE * HEADER_SECTORS)
        if len(header) < SECTOR_SIZE * HEADER_SECTORS:
            # Pad missing header
            self._fh.write(b'\x00' * (SECTOR_SIZE * HEADER_SECTORS - len(header)))
            self._fh.flush()
            header = header + b'\x00' * (SECTOR_SIZE * HEADER_SECTORS - len(header))

        loc_data = header[:SECTOR_SIZE]
        ts_data = header[SECTOR_SIZE:SECTOR_SIZE * 2]

        for i in range(1024):
            entry = loc_data[i * 4: i * 4 + 4]
            offset = (entry[0] << 16) | (entry[1] << 8) | entry[2]
            count = entry[3]
            self._locations[i] = (offset, count)
            if offset > 0 and count > 0:
                for s in range(offset, offset + count):
                    self._sectors_used.add(s)
            self._timestamps[i] = struct.unpack('>I', ts_data[i * 4: i * 4 + 4])[0]

    @staticmethod
    def _index(cx, cz):
        return (cx & 31) + (cz & 31) * 32

    def has_chunk(self, cx, cz):
        with self._lock:
            offset, count = self._locations[self._index(cx, cz)]
            return offset > 0 and count > 0

    def all_chunk_coords(self):
        """Return set of (global_cx, global_cz) for chunks present in this region."""
        out = set()
        if self.rx is None:
            return out
        with self._lock:
            for local_z in range(32):
                for local_x in range(32):
                    offset, count = self._locations[local_x + local_z * 32]
                    if offset > 0 and count > 0:
                        gx = self.rx * 32 + local_x
                        gz = self.rz * 32 + local_z
                        out.add((gx, gz))
        return out

    def read_chunk_raw(self, cx, cz):
        """Return (compression_type, raw_payload_bytes) or None."""
        with self._lock:
            offset, count = self._locations[self._index(cx, cz)]
            if offset == 0 or count == 0:
                return None
            self._fh.seek(offset * SECTOR_SIZE)
            length_bytes = self._fh.read(4)
            if len(length_bytes) < 4:
                return None
            length = struct.unpack('>I', length_bytes)[0]
            if length < 1:
                return None
            comp = self._fh.read(1)[0]
            payload = self._fh.read(length - 1)
            return (comp, payload)

    def read_chunk(self, cx, cz):
        """Return (root_name, CompoundTag) or None if chunk is absent."""
        raw = self.read_chunk_raw(cx, cz)
        if raw is None:
            return None
        comp, payload = raw
        try:
            return nbt_mod.load_compressed_chunk(payload, comp)
        except Exception as e:
            raise IOError(f"Failed to decode chunk ({cx},{cz}) in {self.path.name}: {e}") from e

    def write_chunk(self, cx, cz, name, tag, *, compression_type=2, timestamp=None):
        """Encode and write a chunk. Allocates new sectors if needed."""
        import time
        encoded = nbt_mod.encode_chunk(name, tag, compression_type=compression_type)
        # frame: 4-byte length (length includes compression byte) + 1-byte comp + payload
        frame_size = 4 + 1 + len(encoded)
        sectors_needed = (frame_size + SECTOR_SIZE - 1) // SECTOR_SIZE

        with self._lock:
            idx = self._index(cx, cz)
            old_offset, old_count = self._locations[idx]

            # Free old sectors
            if old_offset > 0 and old_count > 0:
                for s in range(old_offset, old_offset + old_count):
                    self._sectors_used.discard(s)

            # Allocate
            if old_count >= sectors_needed and old_offset > 0:
                # Reuse same slot
                new_offset = old_offset
            else:
                new_offset = self._allocate_sectors(sectors_needed)

            for s in range(new_offset, new_offset + sectors_needed):
                self._sectors_used.add(s)

            # Write frame, padded to sector boundary
            buf = struct.pack('>I', 1 + len(encoded)) + bytes((compression_type,)) + encoded
            pad = sectors_needed * SECTOR_SIZE - len(buf)
            if pad > 0:
                buf += b'\x00' * pad

            self._fh.seek(new_offset * SECTOR_SIZE)
            self._fh.write(buf)

            # Update location table
            self._locations[idx] = (new_offset, sectors_needed)
            loc_entry = bytes((
                (new_offset >> 16) & 0xFF,
                (new_offset >> 8) & 0xFF,
                new_offset & 0xFF,
                sectors_needed & 0xFF,
            ))
            self._fh.seek(idx * 4)
            self._fh.write(loc_entry)

            # Update timestamp
            ts = int(timestamp) if timestamp is not None else int(time.time())
            self._timestamps[idx] = ts
            self._fh.seek(SECTOR_SIZE + idx * 4)
            self._fh.write(struct.pack('>I', ts))

            self._fh.flush()

    def delete_chunk(self, cx, cz):
        with self._lock:
            idx = self._index(cx, cz)
            offset, count = self._locations[idx]
            if offset == 0 and count == 0:
                return False
            for s in range(offset, offset + count):
                self._sectors_used.discard(s)
            self._locations[idx] = (0, 0)
            self._timestamps[idx] = 0
            self._fh.seek(idx * 4)
            self._fh.write(b'\x00\x00\x00\x00')
            self._fh.seek(SECTOR_SIZE + idx * 4)
            self._fh.write(b'\x00\x00\x00\x00')
            self._fh.flush()
            return True

    def _allocate_sectors(self, n):
        """Find the first contiguous run of `n` free sectors at or after sector 2."""
        s = HEADER_SECTORS
        while True:
            run_ok = True
            for k in range(n):
                if (s + k) in self._sectors_used:
                    run_ok = False
                    s = s + k + 1
                    break
            if run_ok:
                return s

    def is_empty(self):
        """Return True if no chunks remain in this region."""
        with self._lock:
            return all(loc == (0, 0) for loc in self._locations)

    def close(self):
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.flush()
                except Exception:
                    pass
                try:
                    self._fh.close()
                except Exception:
                    pass
                self._fh = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def iter_region_files(region_dir):
    """Yield Path objects for all r.x.z.mca files in the directory."""
    p = Path(region_dir)
    if not p.is_dir():
        return
    for f in p.iterdir():
        if f.is_file() and _REGION_NAME_RE.match(f.name):
            yield f
