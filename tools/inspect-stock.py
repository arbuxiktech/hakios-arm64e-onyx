#!/usr/bin/env python3
"""Read stock vendor_boot/DTBO, extract device trees locally, and report board facts.

No Android tools or device access. Source images are opened read-only. Output must
be a new directory; no files in the stock ROM directory are changed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

FDT_MAGIC = 0xD00DFEED
DTBO_MAGIC = 0xD7B7AB1E


def u32(data, offset):
    return struct.unpack_from(">I", data, offset)[0]


def align(value, boundary):
    return (value + boundary - 1) // boundary * boundary


def region(data, start, size):
    if start < 0 or size < 0 or start > len(data) or size > len(data) - start:
        raise ValueError("Image section lies outside its containing file")
    return data[start:start + size]


def fdt_nodes(blob):
    if len(blob) < 40 or u32(blob, 0) != FDT_MAGIC:
        raise ValueError("Not a flattened device tree")
    total, struct_at, strings_at = struct.unpack_from(">III", blob, 4)
    blob = region(blob, 0, total)
    strings = region(blob, strings_at, u32(blob, 32))
    structure = region(blob, struct_at, u32(blob, 36))
    stack, nodes, pos = [], {}, 0
    while pos < len(structure):
        token = u32(structure, pos)
        pos += 4
        if token == 1:  # FDT_BEGIN_NODE
            end = structure.index(b"\0", pos)
            name = structure[pos:end].decode("ascii")
            stack.append(name)
            nodes["/" + "/".join(stack[1:])] = {}
            pos = align(end + 1, 4)
        elif token == 2:
            if not stack:
                raise ValueError("Unbalanced device tree")
            stack.pop()
        elif token == 3:  # FDT_PROP
            if not stack:
                raise ValueError("Property outside a node")
            length, name_at = struct.unpack_from(">II", structure, pos)
            pos += 8
            if name_at >= len(strings):
                raise ValueError("Invalid property name offset")
            name_end = strings.index(b"\0", name_at)
            name = strings[name_at:name_end].decode("ascii")
            nodes["/" + "/".join(stack[1:])][name] = region(structure, pos, length)
            pos = align(pos + length, 4)
        elif token == 4:
            continue
        elif token == 9:
            if stack:
                raise ValueError("Unclosed device tree node")
            return nodes
        else:
            raise ValueError(f"Unknown device tree token {token}")
    raise ValueError("Device tree has no end token")


def dtb_sequence(data):
    pos = 0
    while pos < len(data):
        # Android vendor_boot may hold several concatenated DTBs.
        if data[pos:] == bytes(len(data) - pos):
            return
        if len(data) - pos < 40 or u32(data, pos) != FDT_MAGIC:
            raise ValueError(f"Invalid concatenated DTB at offset {pos}")
        size = u32(data, pos + 4)
        if size < 40:
            raise ValueError("Invalid DTB size")
        yield region(data, pos, size)
        pos += size


def dtbo_entries(data):
    if len(data) < 32 or u32(data, 0) != DTBO_MAGIC:
        raise ValueError("Not an Android DT table")
    total, header, entry_size, count, entries_at, page, version = struct.unpack_from(">7I", data, 4)
    data = region(data, 0, total)
    if header < 32 or entry_size < 32 or count > 4096:
        raise ValueError("Unsupported DT table geometry")
    region(data, entries_at, count * entry_size)
    for i in range(count):
        size, offset, ident, rev, *custom = struct.unpack_from(">8I", data, entries_at + i * entry_size)
        yield {"id": ident, "revision": rev, "custom": custom}, region(data, offset, size)


def describe(value):
    if value and value[0] != 0 and value.endswith(b"\0") and all(c in (0, 9, 10, 13) or 32 <= c <= 126 for c in value):
        return value.rstrip(b"\0").decode("ascii").split("\0")
    if len(value) % 4 == 0:
        return [f"0x{v:x}" for v in struct.unpack(">" + "I" * (len(value) // 4), value)]
    return {"hex": value.hex()}


def interesting(nodes):
    wanted = ("novatek", "touch", "spi@a90000", "interrupt-controller@17100000", "cpu@", "splash", "framebuffer")
    properties = {"compatible", "status", "reg", "model", "qcom,msm-id", "qcom,board-id",
                  "redistributor-stride", "interrupts", "spi-max-frequency", "novatek,irq-gpio",
                  "novatek,reset-gpio", "novatek,lcd_id-gpio1", "novatek,lcd_id-gpio2",
                  "target", "target-path", "enable-method", "capacity-dmips-mhz"}
    selected = {}
    for path, props in nodes.items():
        compatible = props.get("compatible", b"").lower()
        if path == "/" or any(word in path.lower() for word in wanted) or b"novatek" in compatible:
            selected[path] = {key: describe(value) for key, value in props.items() if key in properties}
    return selected


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inspect(images, output):
    if not images.is_dir() or output.exists():
        raise ValueError("Supply an existing images folder and a new output directory")
    if images.resolve() == output.resolve() or images.resolve() in output.resolve().parents:
        raise ValueError("Output must be outside the stock images folder")
    vendor = (images / "vendor_boot.img").read_bytes()
    if vendor[:8] != b"VNDRBOOT":
        raise ValueError("No vendor_boot header")
    version, page = struct.unpack_from("<II", vendor, 8)
    if version not in (3, 4) or page < 512 or page > 65536 or page & (page - 1):
        raise ValueError("Unsupported vendor_boot version or page size")
    ramdisk_size = struct.unpack_from("<I", vendor, 24)[0]
    header_size, dtb_size = struct.unpack_from("<II", vendor, 2096)
    dtb_at = align(header_size, page) + align(ramdisk_size, page)
    trees = [("base-%02d" % i, {}, tree) for i, tree in enumerate(dtb_sequence(region(vendor, dtb_at, dtb_size)))]
    trees += [("overlay-%02d" % i, info, tree) for i, (info, tree) in enumerate(dtbo_entries((images / "dtbo.img").read_bytes()))]
    # Validate everything before creating output.
    decoded = [(name, info, tree, interesting(fdt_nodes(tree))) for name, info, tree in trees]
    report = {"source_directory": str(images.resolve()), "vendor_boot_header_version": version,
              "page_size": page, "trees": [], "input_hashes": {}}
    for name in ("boot.img", "vendor_boot.img", "dtbo.img", "init_boot.img", "xbl_s.melf", "uefi.elf"):
        path = images / name
        if path.is_file():
            report["input_hashes"][name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    output.mkdir(parents=True)
    for name, info, tree, nodes in decoded:
        (output / (name + ".dtb")).write_bytes(tree)
        report["trees"].append({"name": name, "table_entry": info, "bytes": len(tree), "nodes": nodes})
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = inspect(args.images, args.output)
    except (OSError, ValueError, struct.error) as error:
        parser.exit(1, f"Stock inspection failed: {error}\n")
    print(f"Validated and extracted {len(report['trees'])} device trees to {args.output}")


if __name__ == "__main__":
    main()
