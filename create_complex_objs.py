"""Generate complex multi-component OBJ test files for the 3DMax Agent pipeline."""

import math
import os

OUT_DIR = "test_objs"
os.makedirs(OUT_DIR, exist_ok=True)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def box_mesh(x0, y0, z0, W, D, H):
    """Return (vertices, quads) for an axis-aligned box at given origin."""
    v = [
        (x0,     y0,     z0),
        (x0 + W, y0,     z0),
        (x0 + W, y0 + D, z0),
        (x0,     y0 + D, z0),
        (x0,     y0,     z0 + H),
        (x0 + W, y0,     z0 + H),
        (x0 + W, y0 + D, z0 + H),
        (x0,     y0 + D, z0 + H),
    ]
    f = [
        [1, 3, 2], [1, 4, 3],
        [5, 6, 7], [5, 7, 8],
        [1, 2, 6], [1, 6, 5],
        [2, 3, 7], [2, 7, 6],
        [3, 4, 8], [3, 8, 7],
        [4, 1, 5], [4, 5, 8],
    ]
    return v, f


def cylinder_mesh(cx, cy, z0, radius, height, segments=20):
    """Return (vertices, tri-faces) for a cylinder."""
    verts = []
    faces = []
    verts.append((cx, cy, z0))           # bottom centre idx 0
    verts.append((cx, cy, z0 + height))  # top centre    idx 1
    for i in range(segments):
        a = 2 * math.pi * i / segments
        verts.append((cx + radius * math.cos(a), cy + radius * math.sin(a), z0))
    for i in range(segments):
        a = 2 * math.pi * i / segments
        verts.append((cx + radius * math.cos(a), cy + radius * math.sin(a), z0 + height))

    bot = 2
    top = 2 + segments
    for i in range(segments):
        nxt = (i + 1) % segments
        faces.append([1, bot + i, bot + nxt])
        faces.append([2, top + nxt, top + i])
        faces.append([bot + i, bot + nxt, top + nxt])
        faces.append([bot + i, top + nxt, top + i])
    return verts, faces


def merge_meshes(parts):
    """Merge list of (verts, faces) into a single (verts, faces) with re-indexed faces."""
    all_v, all_f = [], []
    offset = 0
    for verts, faces in parts:
        all_v.extend(verts)
        for face in faces:
            all_f.append([i + offset for i in face])
        offset += len(verts)
    return all_v, all_f


def write_obj(filename, vertices, faces, name="object"):
    lines = [f"# {name}", f"o {name}", ""]
    for vx, vy, vz in vertices:
        lines.append(f"v {vx:.3f} {vy:.3f} {vz:.3f}")
    lines.append("")
    for face in faces:
        lines.append("f " + " ".join(str(i + 1) for i in face))
    path = os.path.join(OUT_DIR, filename)
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"  Written: {path}")


# ─── 1. Dining Table — flat top + 4 round legs ───────────────────────────────
# Top: 1200 × 800 × 30 mm  |  Legs: R=30mm, H=720mm
print("Generating complex OBJ files…")

parts = []
# tabletop
parts.append(box_mesh(0, 0, 720, 1200, 800, 30))
# four legs at each corner (inset 50mm)
for lx, ly in [(50, 50), (1150, 50), (50, 750), (1150, 750)]:
    parts.append(cylinder_mesh(lx, ly, 0, 30, 720))

v, f = merge_meshes(parts)
write_obj("dining_table.obj", v, f, "DiningTable")


# ─── 2. Bookshelf Unit — vertical sides + 5 horizontal shelves ───────────────
# Overall: 900 × 300 × 1800 mm  |  18mm MDF panels
parts = []
# Left side panel
parts.append(box_mesh(0,   0, 0, 18,  300, 1800))
# Right side panel
parts.append(box_mesh(882, 0, 0, 18,  300, 1800))
# Top panel
parts.append(box_mesh(18,  0, 1782, 864, 300, 18))
# Bottom panel
parts.append(box_mesh(18,  0, 0,    864, 300, 18))
# 4 internal shelves at even intervals
for shelf_z in [360, 720, 1080, 1440]:
    parts.append(box_mesh(18, 0, shelf_z, 864, 300, 18))

v, f = merge_meshes(parts)
write_obj("bookshelf_unit.obj", v, f, "BookshelfUnit")


# ─── 3. Display Podium — large base box + angled sign panel + cylinder column ─
# Base: 800 × 800 × 100 mm
# Column: R=60mm, H=900mm, centred on base
# Sign panel: 600 × 400 × 20mm, tilted 20° (approximated as rotated vertices)
parts = []
# Base box
parts.append(box_mesh(-400, -400, 0, 800, 800, 100))
# Central column
parts.append(cylinder_mesh(0, 0, 100, 60, 900))

# Angled sign panel — tilt 20 degrees around X axis
angle = math.radians(20)
pw, pd, ph = 600, 20, 400
panel_verts_local = [
    (-pw/2, -pd/2, 0), (pw/2, -pd/2, 0), (pw/2, pd/2, 0), (-pw/2, pd/2, 0),
    (-pw/2, -pd/2, ph), (pw/2, -pd/2, ph), (pw/2, pd/2, ph), (-pw/2, pd/2, ph),
]
sign_verts = []
z_base = 1100  # top of column + extra
for (lx, ly, lz) in panel_verts_local:
    # Rotate around X axis
    ry = ly * math.cos(angle) - lz * math.sin(angle)
    rz = ly * math.sin(angle) + lz * math.cos(angle)
    sign_verts.append((lx, ry, rz + z_base))

sign_faces = [
    [0, 2, 1], [0, 3, 2],
    [4, 5, 6], [4, 6, 7],
    [0, 1, 5], [0, 5, 4],
    [1, 2, 6], [1, 6, 5],
    [2, 3, 7], [2, 7, 6],
    [3, 0, 4], [3, 4, 7],
]
parts.append((sign_verts, sign_faces))

v, f = merge_meshes(parts)
write_obj("display_podium.obj", v, f, "DisplayPodium")


# ─── 4. TV Entertainment Unit — large box + 3 drawers + cable cutout box ─────
# Main carcass: 1800 × 450 × 600 mm
# 3 drawer boxes inside: 550 × 400 × 180 mm each
parts = []
# Main carcass walls (hollow — front open)
thick = 18
W, D, H = 1800, 450, 600
# Bottom
parts.append(box_mesh(0, 0, 0, W, D, thick))
# Top
parts.append(box_mesh(0, 0, H - thick, W, D, thick))
# Left side
parts.append(box_mesh(0, 0, 0, thick, D, H))
# Right side
parts.append(box_mesh(W - thick, 0, 0, thick, D, H))
# Back panel
parts.append(box_mesh(thick, D - thick, 0, W - 2*thick, thick, H))
# Middle vertical divider
parts.append(box_mesh(W//2 - thick//2, 0, 0, thick, D, H))

# 3 drawers
dw, dd, dh = 550, 400, 180
for i, dx in enumerate([30, W//2 + 30, W//2 + 30]):
    dz = 30 + i * (dh + 10) if i > 0 else 30
    parts.append(box_mesh(dx, 10, dz, dw, dd, dh))

v, f = merge_meshes(parts)
write_obj("tv_unit.obj", v, f, "TVEntertainmentUnit")


# ─── 5. Mixed Shapes — round table with square shelf + cylinder legs ──────────
# Round table top: disc approximation using thin box (octagonal) + cylinder legs
parts = []
# Table disc top (approx octagon via many thin triangular box slices is complex;
# use a wide cylinder for the top instead)
parts.append(cylinder_mesh(600, 600, 720, 500, 25, segments=32))  # disc top R=500mm
# 4 tapered cylinder legs (all same size for fabrication)
for lx, ly in [(200, 200), (1000, 200), (1000, 1000), (200, 1000)]:
    parts.append(cylinder_mesh(lx, ly, 0, 35, 720, segments=16))
# Lower circular shelf
parts.append(cylinder_mesh(600, 600, 350, 300, 20, segments=32))

v, f = merge_meshes(parts)
write_obj("round_table_with_shelf.obj", v, f, "RoundTableWithShelf")

print(f"\nDone — 5 complex OBJ files saved to {OUT_DIR}/")
print("\nSuggested upload unit: mm for all files")
