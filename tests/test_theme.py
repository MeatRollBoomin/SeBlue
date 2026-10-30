"""Offline checks for palette, accent contrast, and Windows theme parsing."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from multiblu.theme import (DEFAULT_ACCENT, Theme, abgr_to_hex, blend,
                            contrast_ink, contrast_ratio, palette_for,
                            readable_accent, read_theme)

fails = []


def check(name, ok, detail=""):
    print("  %-48s %s %s" % (name, "PASS" if ok else "FAIL", detail), flush=True)
    if not ok:
        fails.append(name)


print("\n--- registry colour decoding ---", flush=True)
check("ABGR accent decodes to RGB", abgr_to_hex(0xFF1A24E2) == "#E2241A",
      abgr_to_hex(0xFF1A24E2))
check("missing accent stays missing", abgr_to_hex(None) is None)
check("alpha byte is ignored", abgr_to_hex(0x001A24E2) == "#E2241A")

print("\n--- blending and contrast ---", flush=True)
check("blend at 0 returns the first colour", blend("#000000", "#FFFFFF", 0) == "#000000")
check("blend at 1 returns the second colour", blend("#000000", "#FFFFFF", 1) == "#ffffff")
check("blend clamps below zero", blend("#000000", "#FFFFFF", -1) == "#000000")
check("blend clamps above one", blend("#000000", "#FFFFFF", 2) == "#ffffff")
check("black/white contrast is maximal",
      abs(contrast_ratio("#000000", "#FFFFFF") - 21.0) < 0.01)
check("black ink on white", contrast_ink("#FFFFFF") == "#000000")
check("white ink on black", contrast_ink("#000000") == "#FFFFFF")

print("\n--- accent readability ---", flush=True)
for dark in (True, False):
    palette = palette_for(dark, DEFAULT_ACCENT)
    for accent in ("#E2241A", "#3ED598", "#FFD700", "#0067C0", "#FFFFFF",
                   "#000000"):
        p = palette_for(dark, accent)
        bg, card = p["bg"], p["card"]
        ok = all(contrast_ratio(p["accent_fg"], surface) >= 4.0
                 for surface in (bg, card))
        check("%s accent %s is readable on bg/card"
              % ("dark" if dark else "light", accent), ok,
              p["accent_fg"])
    check("%s palette text is readable"
          % ("dark" if dark else "light"),
          contrast_ratio(palette["text"], palette["bg"]) >= 7.0)

print("\n--- palette selection ---", flush=True)
dark = palette_for(True, DEFAULT_ACCENT)
light = palette_for(False, DEFAULT_ACCENT)
check("dark and light backgrounds differ", dark["bg"] != light["bg"])
check("dark cards are darker than text",
      contrast_ratio(dark["card"], dark["text"]) > 7.0)
check("light cards are lighter than text",
      contrast_ratio(light["card"], light["text"]) > 7.0)
check("accent ink is set", dark["accent_ink"] in ("#000000", "#FFFFFF"))
check("explicit accent overrides the default",
      dark["accent"] == DEFAULT_ACCENT and
      palette_for(True, "#123456")["accent"] == "#123456")

print("\n--- live theme state ---", flush=True)
theme = Theme(dark=True, accent="#E2241A", transparency=True)
check("state tuple carries all change triggers",
      theme.state() == (True, "#E2241A", True))
check("state tuple changes with accent",
      theme.state() != Theme(True, "#3ED598", True).state())
check("palette follows the theme", theme.palette()["bg"] == "#0B0C0F")

current = read_theme()
check("read_theme returns a Theme", isinstance(current, Theme))
check("read_theme returns a valid accent",
      len(current.accent) == 7 and current.accent.startswith("#"),
      current.accent)
check("read_theme returns booleans",
      isinstance(current.dark, bool) and isinstance(current.transparency, bool),
      current)

print("\n%s" % ("ALL PASS" if not fails else "FAILURES: %s" % fails), flush=True)
sys.exit(1 if fails else 0)
