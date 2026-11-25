#!/usr/bin/env bash
# samdex dex-pull-donor.sh
#
# Run this on your PC (NOT in this session) with `adb` installed and the
# S26 connected over USB with USB debugging on. No root needed: system
# APKs are normally world-readable, so plain `adb pull` reaches them.
#
# Pulls candidate DeX-related system APKs/jars off a One UI 9.5 device so
# they can be analyzed with `python3 -m samdex ...` (upload the resulting
# donor/ folder, or just the handful of files it actually finds).
#
# Usage:  bash dex-pull-donor.sh [output-dir]

set -u
OUT="${1:-donor-s26-9.5}"
mkdir -p "$OUT"

if ! command -v adb >/dev/null 2>&1; then
  echo "adb not found. Install Android platform-tools first." >&2
  exit 1
fi

echo "== waiting for device =="
adb wait-for-device
adb get-state >/dev/null 2>&1 || { echo "no device/emulator found via adb" >&2; exit 1; }

echo "== model =="
adb shell getprop ro.product.model
adb shell getprop ro.build.version.oneui 2>/dev/null
adb shell getprop ro.build.version.sdk

echo "== discovering candidate packages =="
PKG_LIST=$(adb shell pm list packages -f 2>/dev/null | tr -d '\r')
echo "$PKG_LIST" > "$OUT/pm_list_packages_full.txt"

CANDIDATES=$(echo "$PKG_LIST" | grep -iE \
  'dex|desktopmode|desktop_mode|systemui|sec\.internet|browser|android\.internet' \
  || true)
echo "$CANDIDATES" > "$OUT/pm_list_packages_filtered.txt"
echo "-- candidate packages (also saved to $OUT/pm_list_packages_filtered.txt) --"
echo "$CANDIDATES"

# pm list packages -f lines look like: package:/path/to/app.apk=com.pkg.name
echo "== pulling candidate APKs =="
echo "$CANDIDATES" | sed -n 's/^package:\(.*\)=.*/\1/p' | while read -r apkpath; do
  [ -z "$apkpath" ] && continue
  name=$(basename "$apkpath")
  dest="$OUT/$(echo "$apkpath" | sed 's#^/##;s#/#__#g')"
  echo "pulling $apkpath -> $dest"
  adb pull "$apkpath" "$dest" 2>>"$OUT/pull_errors.log"
done

echo "== best-effort: floating_feature / boot classpath jars (may fail without root, that's fine) =="
for p in /vendor/etc/floating_feature.xml /system/etc/floating_feature.xml \
         /system/framework/services.jar /system/framework/framework.jar; do
  dest="$OUT/$(echo "$p" | sed 's#^/##;s#/#__#g')"
  adb pull "$p" "$dest" 2>>"$OUT/pull_errors.log" && echo "got $p" || echo "skip (denied/absent): $p"
done

echo "== done =="
echo "Results in: $OUT/"
echo "Zip it and share back, or just share whichever *.apk/*.jar actually downloaded:"
echo "  zip -r ${OUT}.zip $OUT"
