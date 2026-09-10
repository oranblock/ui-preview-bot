#!/usr/bin/env bash
# Render Snippet.swift to a PNG on macOS.
#
# There is no Linux path here and there never will be: SwiftUI has no Linux
# implementation, so the Apple half of this bot costs macOS runner minutes while
# the Compose half runs free. That asymmetry is the defining constraint of the
# whole system, not an implementation detail.
#
# swiftui-render is a 4-star project, so it is treated as the fast path and not
# as a dependency: if it fails to build or fails to render, we fall back to a
# self-contained ImageRenderer host, which uses nothing but the SDK.
set +e
cd "$(dirname "$0")"

case "${PREVIEW_DEVICE:-phone}" in
  tablet) W=834; H=1194 ;;
  *)      W=390; H=844  ;;
esac
[ "${PREVIEW_THEME:-dark}" = light ] && SCHEME=light || SCHEME=dark

OUT="$PWD/preview.png"
rm -f "$OUT"

if [ -x /tmp/sr/.build/release/swiftui-render ]; then
  /tmp/sr/.build/release/swiftui-render Snippet.swift \
    --width "$W" --height "$H" --"$SCHEME" -o "$OUT" > render.log 2>&1
  [ -s "$OUT" ] && { echo "rendered via swiftui-render"; exit 0; }
  echo "swiftui-render produced nothing, falling back" >> render.log
fi

# Fallback: compile the snippet together with a tiny host that calls
# ImageRenderer. Fewer views render correctly than under Catalyst, but it
# depends on nothing outside the SDK, so it cannot break because someone else
# pushed to their repo.
cat > Host.swift <<'SWIFT'
import SwiftUI
import AppKit

// @main, not top-level code: `swiftc -parse-as-library` rejects top-level
// expressions, and without -parse-as-library the snippet's own declarations
// collide with implicit main.
@main
struct Host {
  @MainActor static func main() {
    let w = Double(ProcessInfo.processInfo.environment["W"] ?? "390")!
    let h = Double(ProcessInfo.processInfo.environment["H"] ?? "844")!
    let dark = ProcessInfo.processInfo.environment["SCHEME"] != "light"
    let view = Preview()
        .frame(width: w, height: h)
        .environment(\.colorScheme, dark ? .dark : .light)
        .background(dark ? Color.black : Color.white)
    let r = ImageRenderer(content: view)
    r.scale = 2
    guard let img = r.nsImage,
          let tiff = img.tiffRepresentation,
          let rep = NSBitmapImageRep(data: tiff),
          let png = rep.representation(using: .png, properties: [:]) else {
        FileHandle.standardError.write("ImageRenderer produced no image\n".data(using: .utf8)!)
        exit(2)
    }
    try? png.write(to: URL(fileURLWithPath: ProcessInfo.processInfo.environment["OUT"]!))
  }
}
SWIFT

W=$W H=$H SCHEME=$SCHEME OUT=$OUT \
  swiftc -O -parse-as-library Snippet.swift Host.swift -o host >> render.log 2>&1 \
  && W=$W H=$H SCHEME=$SCHEME OUT=$OUT ./host >> render.log 2>&1

[ -s "$OUT" ] && { echo "rendered via ImageRenderer fallback"; exit 0; }
echo "both renderers failed"; tail -20 render.log; exit 1
