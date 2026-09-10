#!/usr/bin/env python3
"""Turn a real source file into something the render scaffold can call.

A pasted snippet can be told to define `Preview()`. A real file cannot: it
arrives with its own package line, its own imports, and several composables or
views named whatever the author wanted. So find the entry point instead of
demanding one.

Usage: prepare.py <in> <out> <android|ios>
"""
import re, sys

src = open(sys.argv[1], encoding="utf-8", errors="replace").read()
out, platform = sys.argv[2], sys.argv[3]


def kotlin(s):
    # The scaffold owns the package. A file's own declaration would either
    # conflict or put Preview() somewhere the test cannot see it.
    s = re.sub(r'(?m)^\s*package\s+[\w.]+\s*$', '', s)

    header = [
        "package preview",
        "import androidx.compose.runtime.Composable",
        "import androidx.compose.material3.*",
        "import androidx.compose.foundation.layout.*",
        "import androidx.compose.ui.Modifier",
        "import androidx.compose.ui.unit.dp",
    ]
    # Kotlin tolerates a duplicate import but not a duplicate *wildcard* clash,
    # and re-importing what the file already imports is noise either way.
    existing = set(re.findall(r'(?m)^\s*import\s+([\w.*]+)', s))
    header = [h for h in header
              if not h.startswith("import") or h.split()[1] not in existing]

    if re.search(r'(?m)^\s*(?:@Composable\s+)?(?:private\s+|internal\s+)?fun\s+Preview\s*\(\s*\)', s):
        return "\n".join(header) + "\n" + s

    # Prefer something the author already marked as a preview, then any
    # zero-argument composable. A composable with parameters cannot be called
    # without inventing values for them, so it is skipped rather than guessed at.
    marked = re.search(
        r'@Preview[^\n]*\n(?:@[\w.]+[^\n]*\n)*\s*(?:private\s+|internal\s+)?fun\s+(\w+)\s*\(\s*\)', s)
    any_c = re.search(
        r'@Composable[^\n]*\n(?:@[\w.]+[^\n]*\n)*\s*(?:private\s+|internal\s+)?fun\s+(\w+)\s*\(\s*\)', s)
    hit = marked or any_c
    if not hit:
        sys.exit("no zero-argument @Composable found — the file needs one to render")
    name = hit.group(1)
    print(f"entry point: {name}()", file=sys.stderr)
    return "\n".join(header) + "\n" + s + f"\n\n@Composable\nfun Preview() {{ {name}() }}\n"


def swift(s):
    header = "import SwiftUI\n" if not re.search(r'(?m)^\s*import\s+SwiftUI', s) else ""
    if re.search(r'(?m)^\s*(?:public\s+)?struct\s+Preview\s*:\s*View', s):
        return header + s

    # A View whose stored properties all have defaults can be built as `X()`.
    # One without cannot, and guessing an argument list produces a compiler
    # error that reads like the file is broken when it is only uninstantiable.
    for m in re.finditer(r'(?m)^\s*(?:public\s+)?struct\s+(\w+)\s*:\s*(?:[\w\s,]*\b)?View\b', s):
        name = m.group(1)
        body = s[m.end():]
        depth, end = 0, len(body)
        for i, ch in enumerate(body):
            if ch == '{': depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0: end = i; break
        decl = body[:end]
        # What actually blocks `X()`:
        #   @State / @Environment / @AppStorage etc. do NOT — a property
        #     wrapper supplies its own storage and these views are built with
        #     no arguments everywhere in real SwiftUI code.
        #   `var body: some View {` does NOT — it is computed.
        #   `= something` does NOT — it has a default.
        #   `var x: String?` does NOT — an optional var defaults to nil.
        # Only a bare, non-optional, unwrapped stored property does.
        needs = []
        for line in decl.splitlines():
            t = line.strip()
            if not t or t.startswith("@") or t.startswith("//"):
                continue
            m = re.match(r'(?:public\s+|private\s+|fileprivate\s+|internal\s+)?'
                         r'(?:let|var)\s+(\w+)\s*:\s*(?!some\b)([^\n={]+)$', t)
            if m and not m.group(2).strip().endswith("?"):
                needs.append(m.group(1))
        if needs:
            print(f"skipping {name}: needs {', '.join(needs)}", file=sys.stderr)
            continue
        print(f"entry point: {name}()", file=sys.stderr)
        return header + s + f"\n\nstruct Preview: View {{\n    var body: some View {{ {name}() }}\n}}\n"
    sys.exit("no View that can be built with no arguments — add `struct Preview: View`")


open(out, "w", encoding="utf-8").write(kotlin(src) if platform == "android" else swift(src))
