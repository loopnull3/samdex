#!/sbin/sh
# SamDeX DeX-flag-unlock module installer.
#
# Strategy: copy the REAL floating_feature.xml into this module's own
# /vendor (or /system) mirror, patch just the DEX_MODE line with awk (no
# python/busybox-extras dependency -- this runs inside Magisk's own
# minimal shell), and let Magisk's systemless-overlay mechanism mount the
# patched copy at boot. We never hand-roll a bind mount, so disabling or
# removing the module alone restores stock behaviour, nothing left over.
#
# This is a recon/experiment module, not a guaranteed fix: see module.prop
# and docs/PLAN.md for why (Samsung states the Flip5 DeX omission is
# design/thermal, not just a missing flag).

LOG=/data/local/tmp/samdex-dex-install.log
: > "$LOG"
log() { echo "$*" | tee -a "$LOG"; }

log "samdex dexunlock: installing on $(getprop ro.product.model) / build $(getprop ro.build.version.incremental 2>/dev/null)"

CANDIDATES="/vendor/etc/floating_feature.xml /system/etc/floating_feature.xml /odm/etc/floating_feature.xml"
SRC=""
for p in $CANDIDATES; do
  if [ -f "$p" ]; then
    SRC="$p"
    break
  fi
done

if [ -z "$SRC" ]; then
  ui_print " "
  ui_print "!! floating_feature.xml not found at any known path."
  ui_print "!! Checked: $CANDIDATES"
  ui_print "!! Run bin/dex-recon.sh and share the output before retrying."
  log "ABORT: no floating_feature.xml found"
  abort "samdex: floating_feature.xml not found, see $LOG"
fi
log "source file: $SRC"

DEXLINE=$(grep -o '<[A-Za-z0-9_:.]*COMMON_CONFIG_DEX_MODE[^>]*>[^<]*</[A-Za-z0-9_:.]*>' "$SRC")
if [ -z "$DEXLINE" ]; then
  ui_print " "
  ui_print "!! No SEC_FLOATING_FEATURE_COMMON_CONFIG_DEX_MODE entry in $SRC."
  ui_print "!! DeX gating on this device is NOT a simple floating_feature flag;"
  ui_print "!! this module can't help by itself. See docs/PLAN.md Phase 3"
  ui_print "!! (SystemUI/Settings code-level gate, needs a smali patch)."
  log "ABORT: DEX_MODE key absent from $SRC"
  abort "samdex: DEX_MODE flag not present, see $LOG"
fi
log "existing line: $DEXLINE"

# Destination path relative to its own partition root, so Magisk's module
# mirror (MODPATH/vendor/..., MODPATH/system/...) lines up with the real
# mount point it overlays at boot.
case "$SRC" in
  /vendor/*) REL="vendor${SRC#/vendor}";;
  /odm/*)    REL="odm${SRC#/odm}";;
  *)         REL="system${SRC#/system}";;
esac
DEST="$MODPATH/$REL"
mkdir -p "$(dirname "$DEST")"

awk '
/COMMON_CONFIG_DEX_MODE/ {
  pre = $0
  gsub(/>.*/, ">", pre)
  rest = $0
  sub(/^[^>]*>/, "", rest)
  val = rest
  sub(/<.*/, "", val)
  tailstart = index(rest, "<")
  tail = substr(rest, tailstart)
  if (val !~ /standalone/) {
    if (val == "") { newval = "standalone" } else { newval = val ",standalone" }
  } else { newval = val }
  print pre newval tail
  next
}
{ print }
' "$SRC" > "$DEST"

if [ ! -s "$DEST" ]; then
  ui_print "!! patch produced an empty file, aborting (original left untouched)"
  log "ABORT: awk patch produced empty output"
  abort "samdex: patch failed, see $LOG"
fi

NEWLINE=$(grep -o '<[A-Za-z0-9_:.]*COMMON_CONFIG_DEX_MODE[^>]*>[^<]*</[A-Za-z0-9_:.]*>' "$DEST")
log "patched line:  $NEWLINE"
ui_print " "
ui_print "floating_feature DEX_MODE patched (systemless, via $REL)."
ui_print "before: $DEXLINE"
ui_print "after:  $NEWLINE"
ui_print " "
if [ "$DEXLINE" = "$NEWLINE" ]; then
  ui_print "('standalone' was already present -- no change made.)"
fi
ui_print "Reboot, then check Settings search for 'DeX'. If it's still absent,"
ui_print "this flag alone wasn't the gate -- see docs/PLAN.md Phase 3."

set_perm_recursive "$MODPATH" 0 0 0755 0644
