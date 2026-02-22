# boot.py — runs before code.py on every reset
#
# Remounts CIRCUITPY so code.py can write log files (/log.txt).
#
# SIDE EFFECT: While code is running, the USB drive is read-only on the host
# (you cannot drag-and-drop new files). To edit files via USB:
#   1. Double-tap the reset button → board enters UF2 bootloader
#   2. CIRCUITPY will re-appear as a normal writable drive
#   3. Edit/copy files, then single-tap reset to run code again
#
import storage
storage.remount("/", readonly=False)
