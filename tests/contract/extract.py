"""Reads the iOS app's Swift data types into app_models.json: for each type it decodes from
dreamfeed, its fields, which are optional, and their JSON names. Run it when the app changes:

    python3 tests/contract/extract.py PATH/TO/dream-feed-ios

check.py then checks dreamfeed's replies against it (what the app needs, nothing more).
Types with their own init(from:) are recorded as "custom" and only checked to be objects.
"""
import json
import re
import sys
from pathlib import Path

DECL = re.compile(r"\b(struct|enum)\s+(\w+)\s*(?::\s*([^{]+))?\{")
FIELD = re.compile(r"^\s*(?:@\w+\s+)*(?:public\s+|private\s+|fileprivate\s+)?(let|var)\s+(\w+)\s*:\s*([^=\n{]+?)\s*(=.*)?$")
CASE = re.compile(r'case\s+(\w+)(?:\s*=\s*"([^"]+)")?')


def blocks(text: str):
    """(kind, name, conformances, body, depth path) of every struct/enum, nested ones too."""
    out, stack, i = [], [], 0
    while True:
        m = DECL.search(text, i)
        if not m:
            break
        start, depth, j = m.end(), 1, m.end()
        while depth and j < len(text):
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            j += 1
        body = text[start:j - 1]
        out.append((m.group(1), m.group(2), m.group(3) or "", body, m.start()))
        i = m.end()
    return out


def top_level_lines(body: str):
    """The body's own lines (not those of nested types or functions)."""
    depth, line, lines = 0, "", []
    for ch in body:
        if ch == "{":
            if depth == 0:
                line += "{"              # (marks a computed property: not decoded)
            depth += 1
        elif ch == "}":
            depth -= 1
        elif depth == 0:
            if ch == "\n":
                lines.append(line); line = ""
            else:
                line += ch
    lines.append(line)
    return lines


def main(app: Path) -> None:
    types = {}
    for f in sorted(app.rglob("*.swift")):
        text = re.sub(r"//[^\n]*", "", f.read_text())
        found = blocks(text)
        spans = [(pos, pos + len(body), name) for _, name, _, body, pos in found]
        for kind, name, conf, body, pos in found:
            if "Decodable" not in conf and "Codable" not in conf:
                continue
            outer = [n for (s, e, n) in spans if s < pos < e and n != name]
            qual = ".".join(outer[-1:] + [name])
            if kind == "enum":
                types[qual] = {"kind": "enum"}
                continue
            keys = {}
            ck = re.search(r"enum\s+CodingKeys\s*:[^{]*\{([^}]*)\}", body)
            if ck:
                for c in CASE.finditer(ck.group(1)):
                    keys[c.group(1)] = c.group(2) or c.group(1)
            fields = {}
            for line in top_level_lines(body):
                m = FIELD.match(line)
                if not m or "{" in line:
                    continue
                name_, typ, default = m.group(2), m.group(3).strip(), m.group(4)
                if ck and name_ not in keys:
                    continue                      # (not decoded: CodingKeys leaves it out)
                optional = typ.endswith("?") or default is not None
                fields[keys.get(name_, name_)] = {"type": typ.rstrip("?").strip(), "optional": optional}
            types[qual] = {"kind": "custom" if "init(from decoder" in body else "struct", "fields": fields,
                           "file": str(f.relative_to(app))}
    out = Path(__file__).with_name("app_models.json")
    rev = (app / ".git" / "HEAD").read_text().strip() if (app / ".git" / "HEAD").is_file() else ""
    out.write_text(json.dumps({"from": "dream-feed-ios", "types": types}, indent=1, sort_keys=True) + "\n")
    print(f"{len(types)} types -> {out}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
