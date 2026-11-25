"""Read-only APK signature inspection.

Diagnostic use only: tells you *which* key an APK is signed with (v1/v2/v3
signer certificate fingerprints) so you can tell, before pushing anything
to a device, whether a donor APK is signed by Samsung's platform key or by
some other key. It parses the ZIP central directory and the APK Signing
Block and extracts certificates; it does not alter, strip, transplant or
re-sign anything.

Why this matters for a DeX port: an app signed with the platform key gets
`android.uid.system` / signature-level permissions. A ported APK you
re-sign yourself (with your own debug/release key, or left unsigned for a
Magisk-overlay install) will NOT have those permissions. Expect
`SecurityException` on calls gated by `signature` or `signatureOrSystem`
protection level, and plan around it (drop the feature, or run the module
through a hook framework such as Xposed/LSPosed on a rooted test device)
rather than trying to carry someone else's signature over.
"""

from __future__ import annotations

import hashlib
import struct

SIG_BLOCK_MAGIC = b"APK Sig Block 42"
BLOCK_IDS = {
    0x7109871A: "v2",
    0xF05368C0: "v3",
    0x1B93AD61: "v3.1",
    0x42726577: "verity-padding",
    0x6DFF800D: "source-stamp",
    0x2146444E: "play-metadata",
}


class ApkError(ValueError):
    pass


def find_eocd(data: bytes) -> tuple[int, int, int, int, bytes]:
    """Return (eocd_offset, cd_offset, cd_size, entry_count, comment)."""
    start = max(0, len(data) - 65557)
    pos = data.rfind(b"PK\x05\x06", start)
    while pos >= 0:
        if pos + 22 <= len(data):
            (_sig, _d, _cdd, _n1, n_total, cd_size, cd_off, clen) = struct.unpack_from(
                "<IHHHHIIH", data, pos)
            if pos + 22 + clen == len(data):
                if cd_off == 0xFFFFFFFF:
                    raise ApkError("zip64 archives are not supported")
                return pos, cd_off, cd_size, n_total, data[pos + 22:pos + 22 + clen]
        pos = data.rfind(b"PK\x05\x06", start, pos)
    raise ApkError("end of central directory not found")


def find_signing_block(data: bytes) -> tuple[int, int] | None:
    """Return (start, end) of the APK Signing Block, or None if absent (v1-only APK)."""
    _eocd, cd_off, _cd_size, _n, _c = find_eocd(data)
    if cd_off < 32 or data[cd_off - 16:cd_off] != SIG_BLOCK_MAGIC:
        return None
    (size_footer,) = struct.unpack_from("<Q", data, cd_off - 24)
    start = cd_off - size_footer - 8
    if start < 0:
        raise ApkError("signing block size out of range")
    (size_header,) = struct.unpack_from("<Q", data, start)
    if size_header != size_footer:
        raise ApkError("signing block header/footer size mismatch")
    return start, cd_off


def signing_block_pairs(data: bytes) -> dict[int, bytes]:
    loc = find_signing_block(data)
    if loc is None:
        return {}
    start, end = loc
    p = start + 8
    stop = end - 24
    pairs: dict[int, bytes] = {}
    while p < stop:
        (ln,) = struct.unpack_from("<Q", data, p)
        (pid,) = struct.unpack_from("<I", data, p + 8)
        pairs[pid] = data[p + 12:p + 8 + ln]
        p += 8 + ln
    return pairs


def _lp(buf: bytes, off: int) -> tuple[bytes, int]:
    (n,) = struct.unpack_from("<I", buf, off)
    return buf[off + 4:off + 4 + n], off + 4 + n


def _lp_seq(buf: bytes) -> list[bytes]:
    out = []
    p = 0
    while p < len(buf):
        item, p = _lp(buf, p)
        out.append(item)
    return out


def scheme_certs(value: bytes) -> list[bytes]:
    """DER certificates of every signer in a v2/v3 signing-block value."""
    certs: list[bytes] = []
    signers, _ = _lp(value, 0)
    for signer in _lp_seq(signers):
        signed_data, _ = _lp(signer, 0)
        _digests, p = _lp(signed_data, 0)
        cert_seq, _p2 = _lp(signed_data, p)
        certs.extend(_lp_seq(cert_seq))
    return certs


# --- minimal DER walker, just enough to pull certs out of a PKCS#7 v1 blob --

def _der(buf: bytes, off: int) -> tuple[int, int, int]:
    """Return (tag, content_offset, content_end)."""
    tag = buf[off]
    ln = buf[off + 1]
    p = off + 2
    if ln & 0x80:
        k = ln & 0x7F
        ln = int.from_bytes(buf[p:p + k], "big")
        p += k
    return tag, p, p + ln


def pkcs7_certs(der: bytes) -> list[bytes]:
    # ContentInfo ::= SEQUENCE { contentType OID, [0] EXPLICIT SignedData }
    _t, p, _e = _der(der, 0)
    _t, _cp, ce = _der(der, p)               # contentType OID
    _t, p, _ = _der(der, ce)                 # [0] EXPLICIT
    _t, p, sd_end = _der(der, p)              # SignedData ::= SEQUENCE
    _t, _cp, ce = _der(der, p)                # version
    _t, _cp, ce = _der(der, ce)               # digestAlgorithms SET
    _t, _cp, ce = _der(der, ce)               # encapContentInfo
    out: list[bytes] = []
    if ce < sd_end and der[ce] == 0xA0:       # [0] IMPLICIT certificates
        _t, p, cend = _der(der, ce)
        while p < cend:
            _t, cp, e = _der(der, p)
            out.append(der[p:e])
            p = e
    return out


def cert_fingerprint(der_cert: bytes) -> str:
    return hashlib.sha256(der_cert).hexdigest()


def describe(path: str) -> dict:
    """Signing-scheme summary for one APK: which schemes are present and
    the SHA-256 fingerprint of each signer's certificate. Read-only."""
    import zipfile

    with open(path, "rb") as fh:
        data = fh.read()

    schemes: dict[str, list[str]] = {}
    pairs = signing_block_pairs(data)
    for block_id, value in pairs.items():
        tag = BLOCK_IDS.get(block_id)
        if tag in ("v2", "v3", "v3.1"):
            schemes[tag] = [cert_fingerprint(c) for c in scheme_certs(value)]

    if not schemes:
        try:
            with zipfile.ZipFile(path) as zf:
                sf_name = next((n for n in zf.namelist()
                                if n.startswith("META-INF/") and n.endswith((".RSA", ".DSA", ".EC"))), None)
                if sf_name:
                    schemes["v1"] = [cert_fingerprint(c) for c in pkcs7_certs(zf.read(sf_name))]
        except (zipfile.BadZipFile, ApkError):
            pass

    return {"path": path, "schemes": schemes, "unsigned": not schemes}
