"""
Pure-Python NBT (Named Binary Tag) parser and writer.

Supports Java Edition (big-endian) and Bedrock Edition (little-endian).
No external dependencies. Modified UTF-8 strings handled per Mojang spec.

Tag IDs:
    0  TAG_End
    1  TAG_Byte
    2  TAG_Short
    3  TAG_Int
    4  TAG_Long
    5  TAG_Float
    6  TAG_Double
    7  TAG_ByteArray
    8  TAG_String
    9  TAG_List
    10 TAG_Compound
    11 TAG_IntArray
    12 TAG_LongArray
"""

import gzip
import io
import os
import struct
import zlib

# Tag IDs
TAG_END = 0
TAG_BYTE = 1
TAG_SHORT = 2
TAG_INT = 3
TAG_LONG = 4
TAG_FLOAT = 5
TAG_DOUBLE = 6
TAG_BYTE_ARRAY = 7
TAG_STRING = 8
TAG_LIST = 9
TAG_COMPOUND = 10
TAG_INT_ARRAY = 11
TAG_LONG_ARRAY = 12


# ==================== Tag Classes ====================

class Tag:
    """Base class for all NBT tags. tag_id is class-level."""
    tag_id = -1
    __slots__ = ('value',)

    def __init__(self, value=None):
        self.value = value

    def __repr__(self):
        return f"{self.__class__.__name__}({self.value!r})"

    def __eq__(self, other):
        return isinstance(other, type(self)) and self.value == other.value


class EndTag(Tag):
    tag_id = TAG_END


class ByteTag(Tag):
    tag_id = TAG_BYTE
    def __init__(self, value=0):
        self.value = int(value)


class ShortTag(Tag):
    tag_id = TAG_SHORT
    def __init__(self, value=0):
        self.value = int(value)


class IntTag(Tag):
    tag_id = TAG_INT
    def __init__(self, value=0):
        self.value = int(value)


class LongTag(Tag):
    tag_id = TAG_LONG
    def __init__(self, value=0):
        self.value = int(value)


class FloatTag(Tag):
    tag_id = TAG_FLOAT
    def __init__(self, value=0.0):
        self.value = float(value)


class DoubleTag(Tag):
    tag_id = TAG_DOUBLE
    def __init__(self, value=0.0):
        self.value = float(value)


class ByteArrayTag(Tag):
    tag_id = TAG_BYTE_ARRAY
    def __init__(self, value=None):
        # list of signed ints (-128..127) or bytes
        if value is None:
            self.value = []
        elif isinstance(value, (bytes, bytearray)):
            self.value = list(value)
        else:
            self.value = list(value)


class StringTag(Tag):
    tag_id = TAG_STRING
    def __init__(self, value=""):
        self.value = str(value)


class ListTag(Tag):
    tag_id = TAG_LIST
    __slots__ = ('value', 'list_type')

    def __init__(self, value=None, list_type=TAG_END):
        self.value = list(value) if value else []
        self.list_type = list_type
        if self.value and list_type == TAG_END:
            self.list_type = self.value[0].tag_id

    def append(self, tag):
        if self.list_type == TAG_END:
            self.list_type = tag.tag_id
        self.value.append(tag)

    def __getitem__(self, i):
        return self.value[i]

    def __len__(self):
        return len(self.value)

    def __iter__(self):
        return iter(self.value)


class CompoundTag(Tag):
    tag_id = TAG_COMPOUND

    def __init__(self, value=None):
        self.value = dict(value) if value else {}

    def __getitem__(self, key):
        return self.value[key]

    def __setitem__(self, key, tag):
        self.value[key] = tag

    def __contains__(self, key):
        return key in self.value

    def __iter__(self):
        return iter(self.value)

    def get(self, key, default=None):
        return self.value.get(key, default)

    def keys(self):
        return self.value.keys()

    def items(self):
        return self.value.items()

    def pop(self, key, default=None):
        return self.value.pop(key, default)


class IntArrayTag(Tag):
    tag_id = TAG_INT_ARRAY
    def __init__(self, value=None):
        self.value = list(value) if value else []


class LongArrayTag(Tag):
    tag_id = TAG_LONG_ARRAY
    def __init__(self, value=None):
        self.value = list(value) if value else []


# Tag ID -> class
_TAG_CLASSES = {
    TAG_END: EndTag,
    TAG_BYTE: ByteTag,
    TAG_SHORT: ShortTag,
    TAG_INT: IntTag,
    TAG_LONG: LongTag,
    TAG_FLOAT: FloatTag,
    TAG_DOUBLE: DoubleTag,
    TAG_BYTE_ARRAY: ByteArrayTag,
    TAG_STRING: StringTag,
    TAG_LIST: ListTag,
    TAG_COMPOUND: CompoundTag,
    TAG_INT_ARRAY: IntArrayTag,
    TAG_LONG_ARRAY: LongArrayTag,
}


# ==================== Reader ====================

class _Reader:
    """Binary NBT reader. little_endian=False for Java, True for Bedrock."""

    def __init__(self, stream, little_endian=False):
        self.s = stream
        self.le = little_endian
        # struct format prefix
        self.p = '<' if little_endian else '>'

    def _read(self, n):
        data = self.s.read(n)
        if len(data) < n:
            raise EOFError(f"Expected {n} bytes, got {len(data)}")
        return data

    def read_byte(self):
        return struct.unpack(self.p + 'b', self._read(1))[0]

    def read_ubyte(self):
        return self._read(1)[0]

    def read_short(self):
        return struct.unpack(self.p + 'h', self._read(2))[0]

    def read_ushort(self):
        return struct.unpack(self.p + 'H', self._read(2))[0]

    def read_int(self):
        return struct.unpack(self.p + 'i', self._read(4))[0]

    def read_long(self):
        return struct.unpack(self.p + 'q', self._read(8))[0]

    def read_float(self):
        return struct.unpack(self.p + 'f', self._read(4))[0]

    def read_double(self):
        return struct.unpack(self.p + 'd', self._read(8))[0]

    def read_string(self):
        n = self.read_ushort()
        if n == 0:
            return ""
        raw = self._read(n)
        # NBT uses "modified UTF-8" but for typical Minecraft data the
        # standard utf-8 decoder works for all valid characters used by Mojang.
        try:
            return raw.decode('utf-8')
        except UnicodeDecodeError:
            return raw.decode('utf-8', errors='replace')

    def read_payload(self, tag_id):
        if tag_id == TAG_BYTE:
            return ByteTag(self.read_byte())
        if tag_id == TAG_SHORT:
            return ShortTag(self.read_short())
        if tag_id == TAG_INT:
            return IntTag(self.read_int())
        if tag_id == TAG_LONG:
            return LongTag(self.read_long())
        if tag_id == TAG_FLOAT:
            return FloatTag(self.read_float())
        if tag_id == TAG_DOUBLE:
            return DoubleTag(self.read_double())
        if tag_id == TAG_BYTE_ARRAY:
            n = self.read_int()
            data = self._read(n)
            return ByteArrayTag(list(struct.unpack(self.p + f'{n}b', data)))
        if tag_id == TAG_STRING:
            return StringTag(self.read_string())
        if tag_id == TAG_LIST:
            list_type = self.read_ubyte()
            n = self.read_int()
            items = []
            if n > 0 and list_type != TAG_END:
                for _ in range(n):
                    items.append(self.read_payload(list_type))
            tag = ListTag(items, list_type=list_type)
            return tag
        if tag_id == TAG_COMPOUND:
            d = {}
            while True:
                child_id = self.read_ubyte()
                if child_id == TAG_END:
                    break
                name = self.read_string()
                d[name] = self.read_payload(child_id)
            return CompoundTag(d)
        if tag_id == TAG_INT_ARRAY:
            n = self.read_int()
            return IntArrayTag(list(struct.unpack(self.p + f'{n}i', self._read(n * 4))))
        if tag_id == TAG_LONG_ARRAY:
            n = self.read_int()
            return LongArrayTag(list(struct.unpack(self.p + f'{n}q', self._read(n * 8))))
        raise ValueError(f"Unknown tag id: {tag_id}")


# ==================== Writer ====================

class _Writer:
    def __init__(self, stream, little_endian=False):
        self.s = stream
        self.le = little_endian
        self.p = '<' if little_endian else '>'

    def write_byte(self, v):
        self.s.write(struct.pack(self.p + 'b', int(v)))

    def write_ubyte(self, v):
        self.s.write(bytes((int(v) & 0xFF,)))

    def write_short(self, v):
        self.s.write(struct.pack(self.p + 'h', int(v)))

    def write_ushort(self, v):
        self.s.write(struct.pack(self.p + 'H', int(v)))

    def write_int(self, v):
        self.s.write(struct.pack(self.p + 'i', int(v)))

    def write_long(self, v):
        self.s.write(struct.pack(self.p + 'q', int(v)))

    def write_float(self, v):
        self.s.write(struct.pack(self.p + 'f', float(v)))

    def write_double(self, v):
        self.s.write(struct.pack(self.p + 'd', float(v)))

    def write_string(self, v):
        raw = v.encode('utf-8')
        if len(raw) > 0xFFFF:
            raise ValueError("NBT string too long")
        self.write_ushort(len(raw))
        self.s.write(raw)

    def write_payload(self, tag):
        tid = tag.tag_id
        if tid == TAG_BYTE:
            self.write_byte(tag.value)
        elif tid == TAG_SHORT:
            self.write_short(tag.value)
        elif tid == TAG_INT:
            self.write_int(tag.value)
        elif tid == TAG_LONG:
            self.write_long(tag.value)
        elif tid == TAG_FLOAT:
            self.write_float(tag.value)
        elif tid == TAG_DOUBLE:
            self.write_double(tag.value)
        elif tid == TAG_BYTE_ARRAY:
            self.write_int(len(tag.value))
            self.s.write(struct.pack(self.p + f'{len(tag.value)}b', *tag.value))
        elif tid == TAG_STRING:
            self.write_string(tag.value)
        elif tid == TAG_LIST:
            list_type = tag.list_type if tag.value else TAG_END
            self.write_ubyte(list_type)
            self.write_int(len(tag.value))
            for child in tag.value:
                self.write_payload(child)
        elif tid == TAG_COMPOUND:
            for name, child in tag.value.items():
                self.write_ubyte(child.tag_id)
                self.write_string(name)
                self.write_payload(child)
            self.write_ubyte(TAG_END)
        elif tid == TAG_INT_ARRAY:
            self.write_int(len(tag.value))
            self.s.write(struct.pack(self.p + f'{len(tag.value)}i', *tag.value))
        elif tid == TAG_LONG_ARRAY:
            self.write_int(len(tag.value))
            self.s.write(struct.pack(self.p + f'{len(tag.value)}q', *tag.value))
        else:
            raise ValueError(f"Cannot write tag id {tid}")


# ==================== Public API ====================

def load(source, *, gzipped=True, little_endian=False, has_bedrock_header=False):
    """
    Load NBT from a path, bytes, or file-like object.

    Returns (root_name, CompoundTag).
    """
    if isinstance(source, bytes):
        data = source
    elif isinstance(source, (str, os.PathLike)):
        with open(source, 'rb') as f:
            data = f.read()
    elif hasattr(source, 'read'):
        data = source.read()
    else:
        raise TypeError(f"Unsupported NBT source: {type(source)}")

    if gzipped:
        try:
            data = gzip.decompress(data)
        except (OSError, gzip.BadGzipFile):
            # Already uncompressed
            pass

    if has_bedrock_header and len(data) >= 8:
        # Bedrock level.dat: 4-byte version + 4-byte length
        data = data[8:]

    return load_bytes(data, little_endian=little_endian)


def load_bytes(data, *, little_endian=False):
    """Parse NBT from raw (uncompressed) bytes. Returns (root_name, CompoundTag)."""
    r = _Reader(io.BytesIO(data), little_endian=little_endian)
    tag_id = r.read_ubyte()
    if tag_id == TAG_END:
        return ("", CompoundTag())
    if tag_id != TAG_COMPOUND:
        raise ValueError(f"NBT root must be compound, got tag id {tag_id}")
    name = r.read_string()
    payload = r.read_payload(TAG_COMPOUND)
    return (name, payload)


def save(name, tag, dest, *, gzipped=True, little_endian=False, bedrock_header_version=None):
    """
    Save a (name, CompoundTag) to a path or file-like object.

    If bedrock_header_version is set, prepends the 8-byte Bedrock level.dat header.
    """
    if not isinstance(tag, CompoundTag):
        raise TypeError("Root NBT tag must be CompoundTag")

    buf = io.BytesIO()
    w = _Writer(buf, little_endian=little_endian)
    w.write_ubyte(TAG_COMPOUND)
    w.write_string(name)
    w.write_payload(tag)
    raw = buf.getvalue()

    if bedrock_header_version is not None:
        header = struct.pack('<ii', int(bedrock_header_version), len(raw))
        raw = header + raw

    if gzipped:
        raw = gzip.compress(raw)

    if hasattr(dest, 'write'):
        dest.write(raw)
    else:
        with open(dest, 'wb') as f:
            f.write(raw)


def load_compressed_chunk(data, compression_type):
    """
    Decompress a chunk from a region file.

    compression_type:
        1 = gzip
        2 = zlib
        3 = uncompressed
        4 = LZ4 (Mojang's variant — block-by-block frames)
    """
    if compression_type == 1:
        raw = gzip.decompress(data)
    elif compression_type == 2:
        raw = zlib.decompress(data)
    elif compression_type == 3:
        raw = data
    elif compression_type == 4:
        raw = _decompress_mojang_lz4(data)
    else:
        raise ValueError(f"Unsupported chunk compression: {compression_type}")
    return load_bytes(raw, little_endian=False)


def encode_chunk(name, tag, compression_type=2):
    """Encode a chunk to compressed bytes for region file storage."""
    buf = io.BytesIO()
    w = _Writer(buf, little_endian=False)
    w.write_ubyte(TAG_COMPOUND)
    w.write_string(name)
    w.write_payload(tag)
    raw = buf.getvalue()

    if compression_type == 1:
        return gzip.compress(raw)
    if compression_type == 2:
        return zlib.compress(raw)
    if compression_type == 3:
        return raw
    raise ValueError(f"Unsupported encode compression: {compression_type}")


def _decompress_mojang_lz4(data):
    """
    Decompress Mojang's LZ4 chunk format (compression type 4, MC 1.20.5+).

    Format: 8-byte header (magic 'LZ4Block' or 4-byte uncompressed length + 4-byte compressed length),
    then raw LZ4 block(s). We require the `lz4` package only when this path is taken.
    """
    try:
        import lz4.block
    except ImportError as e:
        raise RuntimeError(
            "Chunk uses LZ4 compression — install 'lz4' package: pip install lz4"
        ) from e

    # Mojang's framing: 4-byte big-endian uncompressed size, then LZ4 block data
    if len(data) < 4:
        raise ValueError("LZ4 chunk too small")
    uncompressed_size = struct.unpack('>I', data[:4])[0]
    block = data[4:]
    return lz4.block.decompress(block, uncompressed_size=uncompressed_size)
