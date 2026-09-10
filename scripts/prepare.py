#!/usr/bin/env python3
"""Turn a source file, or a zip of them, into something the scaffold can call.

  prepare.py <file|dir> <out_dir> <android|ios>

A pasted snippet can be told to define Preview(). A real file cannot: it arrives
with its own package line, its own imports, and several composables or views
named whatever the author chose. So find the entry point instead of demanding
one, and when several files arrive, find which of them holds it.

Helper files keep their own package declaration and are compiled alongside. Only
a small generated shim lives in the scaffold's package and calls across.
"""
import os, re, shutil, sys

src, out, platform = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(out, exist_ok=True)

EXT = ".kt" if platform == "android" else ".swift"


def collect(path):
    """Every source file, entry candidates first is not assumed — order is
    stable so the same zip always picks the same entry point."""
    if os.path.isfile(path):
        return [path]
    hits = []
    for root, dirs, files in os.walk(path):
        # A zip from a Mac or an IDE carries junk that will not compile.
        dirs[:] = [d for d in dirs if d not in ("__MACOSX", ".git", "build", ".gradle")]
        for f in sorted(files):
            if f.endswith(EXT) and not f.startswith("._"):
                hits.append(os.path.join(root, f))
    return sorted(hits)


def kotlin_entry(text):
    """Preview() if present, else the @Preview-marked composable, else the
    first zero-argument one. A composable with parameters cannot be called
    without inventing values, so it is skipped rather than guessed at."""
    if re.search(r'(?m)^\s*(?:@Composable\s+)?(?:private\s+|internal\s+)?fun\s+Preview\s*\(\s*\)', text):
        return "Preview"
    for pat in (r'@Preview[^\n]*\n(?:@[\w.]+[^\n]*\n)*\s*(?:private\s+|internal\s+)?fun\s+(\w+)\s*\(\s*\)',
                r'@Composable[^\n]*\n(?:@[\w.]+[^\n]*\n)*\s*(?:private\s+|internal\s+)?fun\s+(\w+)\s*\(\s*\)'):
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return None


def swift_entry(text):
    """The first View constructible with no arguments.

    What does NOT block `X()`, learned by rejecting every real view twice:
      @State / @Environment / @AppStorage — a property wrapper brings storage
      var body: some View {  — computed, not stored
      = something            — has a default
      var x: String?         — an optional var defaults to nil
    Only a bare, non-optional, unwrapped stored property does.
    """
    if re.search(r'(?m)^\s*(?:public\s+)?struct\s+Preview\s*:\s*View', text):
        return "Preview"
    for m in re.finditer(r'(?m)^\s*(?:public\s+)?struct\s+(\w+)\s*:\s*(?:[\w\s,]*\b)?View\b', text):
        name, body = m.group(1), text[m.end():]
        depth, end = 0, len(body)
        for i, ch in enumerate(body):
            if ch == '{': depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        needs = []
        for line in body[:end].splitlines():
            t = line.strip()
            if not t or t.startswith("@") or t.startswith("//"):
                continue
            mm = re.match(r'(?:public\s+|private\s+|fileprivate\s+|internal\s+)?'
                          r'(?:let|var)\s+(\w+)\s*:\s*(?!some\b)([^\n={]+)$', t)
            if mm and not mm.group(2).strip().endswith("?"):
                needs.append(mm.group(1))
        if needs:
            print(f"skipping {name}: needs {', '.join(needs)}", file=sys.stderr)
            continue
        return name
    return None


files = collect(src)
if not files:
    sys.exit(f"no {EXT} files found")
print(f"{len(files)} source file(s)", file=sys.stderr)

# Gather every candidate first, then choose. Taking the first hit picked the
# leaf: a zip of FleetPanel + Badge yielded Badge, because B sorts before F.
candidates = []                      # (name, file)
texts = {}
for f in files:
    texts[f] = open(f, encoding="utf-8", errors="replace").read()
    hit = kotlin_entry(texts[f]) if platform == "android" else swift_entry(texts[f])
    if hit:
        candidates.append((hit, f))

entry = entry_file = None
if candidates:
    # An explicit choice always wins, so a zip whose root cannot be guessed is
    # still renderable: send it with ENTRY=MyView.
    want = os.environ.get("ENTRY", "").strip()
    for name, f in candidates:
        if name == want:
            entry, entry_file = name, f
            break

    if not entry:
        # Otherwise prefer a ROOT: a view nothing else calls. A leaf like a
        # badge or a row is referenced by its parent; the screen you actually
        # wanted to see is referenced by nobody in the zip.
        def inbound(name, own):
            return sum(len(re.findall(rf'\b{re.escape(name)}\s*\(', t))
                       for f2, t in texts.items() if f2 != own)
        roots = [(n, f) for n, f in candidates if inbound(n, f) == 0]
        if len(candidates) > 1:
            print("candidates: " + ", ".join(
                f"{n}{'' if (n, f) in roots else ' (referenced)'}"
                for n, f in candidates), file=sys.stderr)
        entry, entry_file = (roots or candidates)[0]

if not entry:
    sys.exit("nothing renderable found — need a zero-argument @Composable, "
             "or a View that can be built with no arguments")

print(f"entry point: {entry}() in {os.path.basename(entry_file)}", file=sys.stderr)

KOTLIN_HEADER = [
    "package preview",
    "import androidx.compose.runtime.Composable",
    "import androidx.compose.material3.*",
    "import androidx.compose.foundation.layout.*",
    "import androidx.compose.ui.Modifier",
    "import androidx.compose.ui.unit.dp",
]


def dress(text):
    """Give a bare snippet a package and the usual Compose imports.

    A pasted snippet has neither, and the multi-file rewrite dropped the step
    that added them — every reference in it then failed to resolve, which reads
    like the snippet is broken when it is the scaffold that is.

    A file that already declares a package is someone's real source: leave it
    alone entirely.
    """
    if re.search(r'(?m)^\s*package\s+[\w.]+\s*$', text):
        return text
    have = set(re.findall(r'(?m)^\s*import\s+([\w.*]+)', text))
    head = [h for h in KOTLIN_HEADER
            if not h.startswith("import") or h.split()[1] not in have]
    return "\n".join(head) + "\n\n" + text


# Copy every file through, flattened. Names can collide across directories in a
# zip, so keep the first and warn rather than silently overwriting one.
seen = {}
for f in files:
    base = os.path.basename(f)
    if base in seen:
        print(f"ignoring duplicate {base}", file=sys.stderr)
        continue
    seen[base] = f
    body = texts[f]
    if platform == "android":
        body = dress(body)
    open(os.path.join(out, base), "w", encoding="utf-8").write(body)

if platform == "android":
    pkg = None
    m = re.search(r'(?m)^\s*package\s+([\w.]+)\s*$',
                  open(entry_file, encoding="utf-8", errors="replace").read())
    if m:
        pkg = m.group(1)
    if pkg:
        # The source keeps its own package, so reach it by name rather than
        # rewriting someone's file. When their function is ALSO called Preview,
        # importing it unaliased makes the shim call itself — infinite
        # recursion that compiles cleanly and then blows the stack.
        alias = "RealPreview" if entry == "Preview" else entry
        imp = f"import {pkg}.{entry}" + (f" as {alias}" if alias != entry else "")
        shim = ["package preview",
                "import androidx.compose.runtime.Composable",
                imp, "", "@Composable", f"fun Preview() {{ {alias}() }}"]
        open(os.path.join(out, "PreviewEntry.kt"), "w").write("\n".join(shim) + "\n")
    elif entry != "Preview":
        shim = ["package preview",
                "import androidx.compose.runtime.Composable",
                "", "@Composable", f"fun Preview() {{ {entry}() }}"]
        open(os.path.join(out, "PreviewEntry.kt"), "w").write("\n".join(shim) + "\n")
else:
    # Swift has no per-file namespace, so everything compiled together already
    # sees everything else. Only a shim is needed, and only if the entry point
    # is not already called Preview.
    if entry != "Preview":
        open(os.path.join(out, "PreviewEntry.swift"), "w").write(
            "import SwiftUI\n\nstruct Preview: View {\n"
            f"    var body: some View {{ {entry}() }}\n}}\n")
