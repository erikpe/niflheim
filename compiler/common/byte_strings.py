from __future__ import annotations


def escape_bytes_for_c_string(data: bytes) -> str:
    pieces: list[str] = []
    for byte in data:
        if byte == 0x22:
            pieces.append('\\"')
        elif byte == 0x5C:
            pieces.append('\\\\')
        elif byte == 0x0A:
            pieces.append("\\n")
        elif byte == 0x0D:
            pieces.append("\\r")
        elif byte == 0x09:
            pieces.append("\\t")
        elif 0x20 <= byte <= 0x7E:
            pieces.append(chr(byte))
        else:
            pieces.append(f"\\{byte:03o}")
    return "".join(pieces)


__all__ = ["escape_bytes_for_c_string"]