#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def compare(root: Path) -> dict[str, object]:
    receipts = sorted(root.glob("*/receipts/artifact-inventory.json"))
    if len(receipts) != 6:
        raise ValueError(f"expected six matrix receipts, found {len(receipts)}")
    hashes: dict[str, dict[str, str]] = {}
    for receipt in receipts:
        matrix = receipt.parents[1].name
        inventory = json.loads(receipt.read_text(encoding="utf-8"))
        names = [Path(item["file"]).name for item in inventory]
        wheels = [name for name in names if name.endswith(".whl")]
        sdists = [name for name in names if name.endswith(".tar.gz")]
        if len(inventory) != 2 or len(wheels) != 1 or len(sdists) != 1:
            raise ValueError(f"{matrix} must report exactly one wheel and one sdist")
        if len(set(names)) != len(names):
            raise ValueError(f"{matrix} reports duplicate artifact identities")
        for item in inventory:
            name = Path(item["file"]).name
            hashes.setdefault(name, {})[matrix] = item["sha256"]
    if len(hashes) != 2 or any(len(values) != 6 for values in hashes.values()):
        raise ValueError(
            "every expected artifact must have one hash from each matrix cell"
        )
    failures = {
        name: values
        for name, values in hashes.items()
        if len(set(values.values())) != 1
    }
    if failures:
        raise ValueError(f"artifact hashes differ across supported matrix: {failures}")
    return {
        "schema_version": "pcodex.reproducibility.v1",
        "passed": True,
        "matrix_receipts": len(receipts),
        "artifacts": hashes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = compare(args.root)
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
