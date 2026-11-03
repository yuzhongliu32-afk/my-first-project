"""Review original schema identity and shared definitions without fetching URLs."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harbourline.contracts import check_schemas, schema

check_schemas()
manifest = json.loads((ROOT / "docs/schema_source_manifest.json").read_text())
for entry in manifest:
    path = ROOT / "schemas" / entry["file"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], path.name
full = schema("Full")
for role in ("Common", "A", "B", "C"):
    current = schema(role)
    for name, definition in current["$defs"].items():
        assert definition == full["$defs"][name], (role, name)
    for name, definition in current["properties"].items():
        assert definition == full["properties"][name], (role, name)


def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for child in obj.values():
            yield from walk(child)
    elif isinstance(obj, list):
        for child in obj:
            yield from walk(child)


for role in ("Common", "A", "B", "C", "Full"):
    current = schema(role)
    for obj in walk(current):
        if "$ref" in obj:
            ref = obj["$ref"]
            assert ref.startswith("#/$defs/") and ref[8:] in current["$defs"], ref
print("PASS: five meta-schemas, four original hashes, shared definitions and local references")
