#!/sbin/sh
# Nothing to clean up by hand: this module only ever placed a patched copy
# of floating_feature.xml inside its own Magisk mirror (MODPATH/vendor/...
# or MODPATH/system/...) and let Magisk's systemless overlay mount it.
# Removing/disabling the module removes that overlay and the real,
# original floating_feature.xml on /vendor or /system is unmounted/used
# again automatically on next boot. No manual bind mount, no edited file
# on the real partition -- so there's nothing left to restore here.
echo "samdex dexunlock: uninstalled, original floating_feature.xml is back in effect after reboot" \
  >> /data/local/tmp/samdex-dex-install.log
