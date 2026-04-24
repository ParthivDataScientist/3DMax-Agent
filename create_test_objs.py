"""Generate sample OBJ test files for the 3DMax Agent pipeline."""

import math
import os

OUT_DIR = "test_objs"
os.makedirs(OUT_DIR, exist_ok=True)


def write_obj(filename: str, vertices: list, faces: list, name: str = "object") -> None:
    lines = [f"# {name}", f"o {name}", ""]
    for v in vertices:
        lines.append(f"v {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}")
    lines.append("")
    for f in faces:
        lines.append("f " + " ".join(str(i) for i in f))
    path = os.path.join(OUT_DIR, filename)
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"  Written: {path}")


def box_verts_faces(W, D, H):
    """Axis-aligned box from origin to (W, D, H). Returns (vertices, faces)."""
    v = [
        (0, 0, 0), (W, 0, 0), (W, D, 0), (0, D, 0),  # bottom 1-4
        (0, 0, H), (W, 0, H), (W, D, H), (0, D, H),  # top    5-8
    ]
    f = [
        [1, 3, 2], [1, 4, 3],        # bottom
        [5, 6, 7], [5, 7, 8],        # top
        [1, 2, 6], [1, 6, 5],        # front
        [2, 3, 7], [2, 7, 6],        # right
        [3, 4, 8], [3, 8, 7],        # back
        [4, 1, 5], [4, 5, 8],        # left
    ]
    return v, f


def cylinder_verts_faces(radius, height, segments=24):
    """Cylinder centred at origin, cap at Z=0, top at Z=height."""
    verts = []
    faces = []

    # Bottom cap centre (index 1)
    verts.append((0.0, 0.0, 0.0))
    # Top cap centre (index 2)
    verts.append((0.0, 0.0, height))

    # Bottom ring (indices 3 .. 3+segments-1)
    for i in range(segments):
        angle = 2 * math.pi * i / segments
        verts.append((radius * math.cos(angle), radius * math.sin(angle), 0.0))

    # Top ring (indices 3+segments .. 3+2*segments-1)
    for i in range(segments):
        angle = 2 * math.pi * i / segments
        verts.append((radius * math.cos(angle), radius * math.sin(angle), height))

    bot_off = 2
    top_off = 2 + segments

    for i in range(segments):
        nxt = (i + 1) % segments
        # Bottom cap triangle
        faces.append([1, bot_off + i, bot_off + nxt])
        # Top cap triangle (reversed winding)
        faces.append([2, top_off + nxt, top_off + i])
        # Side quad (two triangles)
        faces.append([bot_off + i, bot_off + nxt, top_off + nxt])
        faces.append([bot_off + i, top_off + nxt, top_off + i])

    return verts, faces


def disc_verts_faces(radius, thickness, segments=24):
    """Flat disc (short cylinder)."""
    return cylinder_verts_faces(radius, thickness, segments)


# ── 1. Simple box 1000 × 500 × 300 mm ────────────────────────────────────────
print("Generating OBJ files…")
v, f = box_verts_faces(1000, 500, 300)
write_obj("box_1000x500x300.obj", v, f, "Box_1000x500x300")

# ── 2. Flat panel 800 × 600 × 18 mm (plywood sheet) ──────────────────────────
v, f = box_verts_faces(800, 600, 18)
write_obj("flat_panel_800x600x18.obj", v, f, "FlatPanel_800x600x18")

# ── 3. Tall cabinet 600 × 400 × 1800 mm ──────────────────────────────────────
v, f = box_verts_faces(600, 400, 1800)
write_obj("cabinet_600x400x1800.obj", v, f, "Cabinet_600x400x1800")

# ── 4. Cylinder R=150 mm, H=600 mm ───────────────────────────────────────────
v, f = cylinder_verts_faces(150, 600)
write_obj("cylinder_r150_h600.obj", v, f, "Cylinder_R150_H600")

# ── 5. Circular disc R=300 mm, thickness=20 mm ───────────────────────────────
v, f = disc_verts_faces(300, 20)
write_obj("disc_r300_t20.obj", v, f, "Disc_R300_T20")

print("Done — all files saved to", OUT_DIR)
