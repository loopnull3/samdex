#!/system/bin/sh
# samdex dex-recon.sh
#
# Read-only recon. Run as root (adb shell + `su`, or Termux `tsu`/`su`)
# on the TARGET DEVICE after it is rooted. It does not change anything on
# the device -- it only dumps candidate gating mechanisms for Samsung DeX
# so we can tell, before patching anything, whether Z Flip5's missing DeX
# menu is:
#   (a) a floating_feature.xml flag            -> magisk-module/ handles it
#   (b) a PackageManager <feature> declaration  -> similar XML-only fix
#   (c) a hard-coded check in SystemUI/Settings code -> needs a smali patch
#
# Usage:  su -c sh dex-recon.sh            (from adb shell or Termux)
# Output: /sdcard/Download/samdex-recon-<timestamp>.txt (and stdout)

TS=$(date +%Y%m%d-%H%M%S)
OUT="/sdcard/Download/samdex-recon-$TS.txt"
: > "$OUT" 2>/dev/null || OUT="/data/local/tmp/samdex-recon-$TS.txt"
: > "$OUT"

say() { echo "$*" | tee -a "$OUT"; }
hr()  { say "----------------------------------------------------------------"; }

say "samdex recon  $(date)"
say "model: $(getprop ro.product.model)  build: $(getprop ro.build.display.id)"
say "oneui: $(getprop ro.build.version.oneui 2>/dev/null)  api: $(getprop ro.build.version.sdk)"
hr

say "## 1. floating_feature.xml (model/hw-gated flags)"
for p in /vendor/etc/floating_feature.xml /system/etc/floating_feature.xml /odm/etc/floating_feature.xml; do
  if [ -f "$p" ]; then
    say "--- $p : present ---"
    grep -iE 'dex|desktop|winset|flip|fold|form_factor' "$p" | tee -a "$OUT"
  else
    say "--- $p : absent ---"
  fi
done
hr

say "## 2. PackageManager <feature> declarations mentioning DeX/desktop"
for d in /system/etc/permissions /system/etc/sysconfig /vendor/etc/permissions \
         /vendor/etc/sysconfig /system_ext/etc/permissions /system_ext/etc/sysconfig \
         /product/etc/permissions /product/etc/sysconfig; do
  [ -d "$d" ] || continue
  grep -rliE 'dex|desktopmode' "$d" 2>/dev/null | while read -r f; do
    say "--- $f ---"
    grep -iE 'dex|desktopmode' "$f" | tee -a "$OUT"
  done
done
say "(live) pm list features | grep -i dex:"
pm list features 2>/dev/null | grep -i dex | tee -a "$OUT"
hr

say "## 3. relevant system properties"
getprop 2>/dev/null | grep -iE 'dex|desktop' | tee -a "$OUT"
hr

say "## 4. string constants in SystemUI / Settings / framework (slow)"
KEYWORDS='DEX_MODE|isDexModeSupported|isDeXSupported|SUPPORT_DESKTOPMODE|DesktopMode|SemFloatingFeature|FLIP|WINSET'
for apk in /system*/priv-app/SystemUI*/SystemUI*.apk \
           /system*/priv-app/*Settings*/*Settings*.apk \
           /system/framework/framework-res.apk \
           /system*/framework/services.jar \
           /system*/framework/framework.jar; do
  for f in $apk; do
    [ -f "$f" ] || continue
    say "--- strings in $f matching ($KEYWORDS) ---"
    { unzip -p "$f" classes*.dex 2>/dev/null; cat "$f" 2>/dev/null; } \
      | strings -n 6 2>/dev/null | grep -iE "$KEYWORDS" | sort -u | tee -a "$OUT"
  done
done
hr

say "Done. Output saved to: $OUT"
say "Pull it with:  adb pull $OUT   (or just share the file from Download/)"
