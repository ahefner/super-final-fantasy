#!/usr/bin/env python3
"""Boot the port, continue the battery save, and open the overworld map.

The minimap is the one screen the CHRDUMP diagnostic cares about, and getting
to it is half a dozen timed keystrokes, so keep them in one place.  Leaves ares
running; the caller decides when to quit it (quitting is what flushes SRAM).
"""
import sys, os, time, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import drive

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def main():
    subprocess.run(["killall", "ares"], capture_output=True); time.sleep(1)
    subprocess.Popen(["/Applications/ares.app/Contents/MacOS/ares",
                      "--system", "Super Famicom", "--no-file-prompt",
                      os.path.join(ROOT, "FinalFantasy.sfc")],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3); drive.activate(); time.sleep(1)

    time.sleep(9)                          # intro
    drive.press("start"); time.sleep(2)
    drive.press("A");     time.sleep(2)    # CONTINUE
    drive.press("A");     time.sleep(3)    # confirm the save
    drive.press("A");     time.sleep(3)    # into the field

    drive.activate(); time.sleep(0.4)      # B + Select opens the overworld map
    subprocess.run(["osascript","-e",'tell application "System Events" to key down "a"'],capture_output=True)
    time.sleep(0.15)
    subprocess.run(["osascript","-e",'tell application "System Events" to key down 48'],capture_output=True)
    time.sleep(0.20)
    subprocess.run(["osascript","-e",'tell application "System Events" to key up 48'],capture_output=True)
    subprocess.run(["osascript","-e",'tell application "System Events" to key up "a"'],capture_output=True)

    time.sleep(14)                         # map, crests and logo all draw
    drive.shot("minimap")

def quit_ares():
    subprocess.run(["osascript","-e",'tell application "ares" to quit'],capture_output=True)
    time.sleep(3)
    subprocess.run(["pkill","-x","ares"], capture_output=True)
    time.sleep(1)

if __name__ == "__main__":
    main(); quit_ares()
