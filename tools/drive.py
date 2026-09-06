#!/usr/bin/env python3
"""
drive.py -- launch the port under ares and play it from a script.

usage:  drive.py "w4, start, w3, down, a, w2, shot:title, ..."

tokens:   w<seconds>     wait
          shot:<name>    screenshot (cropped to the emulator picture)
          <button>       press a button and release it

Buttons use the mapping configured in ares on this machine:
    d-pad = arrow keys, Start = Return, Select = Tab,
    A = 's', B = 'a', Y = 'w', X = 'q'
"""
import ctypes, ctypes.util, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SHOTS = os.environ.get("SHOTDIR", "/tmp")

#  Buttons, as mapped in ares on this machine, given as raw macOS virtual key
#  codes.  Everything goes through CGEvent below rather than AppleScript: System
#  Events' "key down" only accepts a character or a key constant, so
#  "key down 125" for an arrow parsed fine, reported success, and did nothing at
#  all.  Every scripted arrow press was silently dropped, which made the party
#  stand still while the script believed it was walking.
BUTTON = {"A": 1, "B": 0, "Y": 13, "X": 12,        # s, a, w, q
          "start": 36, "select": 48,               # Return, Tab
          "up": 126, "down": 125, "left": 123, "right": 124,
          "savestate": 17, "loadstate": 15}        # t, r

#  How long to hold a button, in seconds.  This matters: the game samples the
#  pad once a frame, so a down-and-up inside 16ms can fall between two polls and
#  never be seen at all.  Seven frames is comfortably caught, and short enough
#  not to auto-repeat in menus.
HOLD = 0.12

_cg = ctypes.cdll.LoadLibrary(ctypes.util.find_library("ApplicationServices"))
_cg.CGEventCreateKeyboardEvent.restype  = ctypes.c_void_p
_cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
_cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
_cg.CFRelease.argtypes   = [ctypes.c_void_p]


def key(code, down):
    """Post a raw key event.  Holding works, which AppleScript cannot do."""
    e = _cg.CGEventCreateKeyboardEvent(None, code, down)
    _cg.CGEventPost(0, e)
    _cg.CFRelease(e)


def hold(button, secs):
    """Hold a button down for a stretch -- what sustained walking needs."""
    activate()
    code = BUTTON[button]
    key(code, True)
    time.sleep(secs)
    key(code, False)
    time.sleep(0.05)


def osa(script):
    subprocess.run(["osascript", "-e", script], capture_output=True)


def activate():
    osa('tell application "ares" to activate')


def press(button, secs=HOLD):
    activate()
    code = BUTTON[button]
    key(code, True)
    time.sleep(secs)
    key(code, False)
    time.sleep(0.05)


def window_rect():
    """Ask the window server where ares put itself, rather than assuming."""
    r = subprocess.run(["osascript", "-e",
        'tell application "System Events" to tell process "ares" '
        'to get {position, size} of window 1'], capture_output=True, text=True)
    try:
        n = [int(v.strip()) for v in r.stdout.strip().split(",")]
        x, y, w, h = n[0], n[1], n[2], n[3]
    except Exception:
        return None
    # trim the title bar and the status strip along the bottom
    return (x, y + 26, w, h - 26 - 26)


def shot(name):
    out = os.path.join(SHOTS, name + ".png")
    rect = window_rect()
    if rect:
        subprocess.run(["screencapture", "-x",
                        "-R%d,%d,%d,%d" % rect, out], check=True)
    else:
        subprocess.run(["screencapture", "-x", out], check=True)
    print("  shot -> %s" % out)


def main():
    script = sys.argv[1] if len(sys.argv) > 1 else "w6, shot:boot"
    subprocess.run(["killall", "ares", "Snes9x"], capture_output=True)
    time.sleep(1)
    subprocess.Popen(["/Applications/ares.app/Contents/MacOS/ares",
                      "--system", "Super Famicom", "--no-file-prompt",
                      os.path.join(ROOT, "FinalFantasy.sfc")]
                     + (["--save-state", os.environ["STATE"]]
                        if os.environ.get("STATE") else []),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    activate()
    time.sleep(1)

    for tok in [t.strip() for t in script.split(",") if t.strip()]:
        if tok.startswith("w"):
            time.sleep(float(tok[1:]))
        elif tok.startswith("shot:"):
            activate(); time.sleep(0.3); shot(tok[5:])
        elif tok in BUTTON:
            activate(); press(tok); time.sleep(0.25)
        elif tok.startswith("down:") or tok.startswith("up:"):
            #  Press and leave held / release, so screenshots can be taken
            #  mid-movement.  Single-frame glitches only show while walking.
            act, b = tok.split(":")
            v = BUTTON[b]
            arg = '"%s"' % v if isinstance(v, str) else str(v)
            activate()
            subprocess.run(["osascript", "-e",
                'tell application "System Events" to key %s %s'
                % ("down" if act == "down" else "up", arg)], capture_output=True)
            time.sleep(0.1)
        elif tok in ("savestate", "loadstate"):
            #  ares hotkeys, bound in its GUI: 't' saves, 'r' restores.
            #  Letters rather than function keys on purpose -- macOS consumes
            #  F5/F7 itself, so they never reach the emulator.
            activate()
            k = "t" if tok == "savestate" else "r"
            subprocess.run(["osascript",
                "-e", 'tell application "System Events" to key down "%s"' % k,
                "-e", "delay 0.12",
                "-e", 'tell application "System Events" to key up "%s"' % k],
                capture_output=True)
            time.sleep(1.2)
        elif tok.startswith("key:"):              # raw key, for emulator hotkeys
            activate()
            k = tok[4:]
            subprocess.run(["osascript",
                "-e", 'tell application "System Events" to key down "%s"' % k,
                "-e", "delay 0.15",
                "-e", 'tell application "System Events" to key up "%s"' % k],
                capture_output=True)
            time.sleep(0.5)
        elif tok.startswith("h"):                 # hold: h<seconds>:<button>
            secs, b = tok[1:].split(":")
            activate(); press(b, hold=float(secs))
        elif tok.startswith("x"):                 # repeat: x<n>:<button>
            n, b = tok[1:].split(":")
            for _ in range(int(n)):
                press(b); time.sleep(0.18)
        else:
            sys.exit("unknown token %r" % tok)
    print("done")


if __name__ == "__main__":
    main()
