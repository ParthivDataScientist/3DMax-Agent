"""Generate a simple connected exhibition booth OBJ test model in millimeters."""

from __future__ import annotations

from pathlib import Path


OUT_DIR = Path("generated_objs")
OUT_PATH = OUT_DIR / "simple_connected_exhibition_booth.obj"
COMPONENT_OFFSET_STEP_MM = 0.017


def box_vertices(x: float, y: float, z: float, width: float, depth: float, height: float) -> list[tuple[float, float, float]]:
    return [
        (x, y, z),
        (x + width, y, z),
        (x + width, y + depth, z),
        (x, y + depth, z),
        (x, y, z + height),
        (x + width, y, z + height),
        (x + width, y + depth, z + height),
        (x, y + depth, z + height),
    ]


BOX_FACES = [
    (1, 3, 2),
    (1, 4, 3),
    (5, 6, 7),
    (5, 7, 8),
    (1, 2, 6),
    (1, 6, 5),
    (2, 3, 7),
    (2, 7, 6),
    (3, 4, 8),
    (3, 8, 7),
    (4, 1, 5),
    (4, 5, 8),
]


def add_box(parts: list[dict], name: str, x: float, y: float, z: float, width: float, depth: float, height: float) -> None:
    # Tiny per-part translation prevents coincident vertices from merging components
    # while overlaps keep the model visually connected.
    offset = len(parts) * COMPONENT_OFFSET_STEP_MM
    parts.append(
        {
            "name": name,
            "vertices": box_vertices(x + offset, y + offset, z + offset, width, depth, height),
            "faces": BOX_FACES,
        }
    )


def build_booth_parts() -> list[dict]:
    parts: list[dict] = []

    # 6 m x 3 m open-front booth, no ceiling. Everything touches the floor/walls/frame.
    booth_w = 6000.0
    booth_d = 3000.0
    floor_t = 30.0
    wall_t = 18.0
    wall_h = 2400.0
    post = 120.0
    base_z = floor_t - 12.0

    add_box(parts, "floor_platform_6000x3000", 0, 0, 0, booth_w, booth_d, floor_t)

    # Three-sided wall shell: back, left, right.
    add_box(parts, "back_wall_panel", 0, booth_d - wall_t, base_z, booth_w, wall_t, wall_h)
    add_box(parts, "left_wall_panel", 0, 0, base_z, wall_t, booth_d, wall_h)
    add_box(parts, "right_wall_panel", booth_w - wall_t, 0, base_z, wall_t, booth_d, wall_h)

    # Square structural posts tied to the walls/floor.
    for name, x, y in [
        ("front_left_square_post", 0, 0),
        ("front_right_square_post", booth_w - post, 0),
        ("back_left_square_post", 0, booth_d - post),
        ("back_right_square_post", booth_w - post, booth_d - post),
        ("mid_back_square_post", (booth_w - post) / 2, booth_d - post),
    ]:
        add_box(parts, name, x, y, base_z, post, post, wall_h + 150)

    # Open top frame/header only, not a ceiling.
    add_box(parts, "front_open_header_beam", 0, 0, floor_t + wall_h, booth_w, post, 180)
    add_box(parts, "back_header_beam", 0, booth_d - post, floor_t + wall_h, booth_w, post, 180)
    add_box(parts, "left_header_beam", 0, 0, floor_t + wall_h, post, booth_d, 180)
    add_box(parts, "right_header_beam", booth_w - post, 0, floor_t + wall_h, post, booth_d, 180)

    # Branding/signage on the back wall.
    add_box(parts, "backlit_brand_sign_panel", 1900, booth_d - wall_t - 35, 1500, 2200, 35, 550)
    add_box(parts, "small_logo_block_left", 2150, booth_d - wall_t - 70, 1675, 180, 35, 180)
    add_box(parts, "small_logo_block_right", 3670, booth_d - wall_t - 70, 1675, 180, 35, 180)

    # Meeting/display table in the booth center.
    add_box(parts, "center_table_top", 2100, 950, 780, 1800, 750, 50)
    add_box(parts, "center_table_left_leg", 2250, 1100, base_z, 120, 120, 730)
    add_box(parts, "center_table_right_leg", 3630, 1100, base_z, 120, 120, 730)
    add_box(parts, "center_table_back_leg", 2940, 1510, base_z, 120, 120, 730)

    # Shoe rack along the right wall with three shelves.
    add_box(parts, "shoe_rack_left_side", 4350, 2180, base_z, 40, 620, 1100)
    add_box(parts, "shoe_rack_right_side", 5650, 2180, base_z, 40, 620, 1100)
    add_box(parts, "shoe_rack_bottom_shelf", 4350, 2180, floor_t + 80, 1340, 620, 40)
    add_box(parts, "shoe_rack_middle_shelf", 4350, 2180, floor_t + 430, 1340, 620, 40)
    add_box(parts, "shoe_rack_top_shelf", 4350, 2180, floor_t + 780, 1340, 620, 40)
    add_box(parts, "shoe_rack_back_panel", 4350, 2760, base_z, 1340, 40, 1100)

    # Reception/demo counter near the open front.
    add_box(parts, "front_demo_counter_body", 500, 500, base_z, 1300, 550, 900)
    add_box(parts, "front_demo_counter_top", 450, 450, floor_t + 900, 1400, 650, 50)

    # Product display shelves mounted to the left wall.
    add_box(parts, "left_display_shelf_lower", wall_t, 720, 850, 1200, 320, 40)
    add_box(parts, "left_display_shelf_upper", wall_t, 720, 1250, 1200, 320, 40)
    add_box(parts, "left_display_vertical_backer", wall_t, 690, 650, 1250, 35, 850)

    # Small brochure stand next to the counter.
    add_box(parts, "brochure_stand_base", 1900, 520, base_z, 300, 300, 60)
    add_box(parts, "brochure_stand_post", 2020, 640, floor_t + 60, 60, 60, 900)
    add_box(parts, "brochure_holder_panel", 1880, 590, floor_t + 650, 340, 40, 420)

    return parts


def write_obj(path: Path, parts: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Simple connected exhibition booth test model",
        "# Units: millimeters",
        "# Open-front 3-sided booth with no ceiling",
        "",
    ]
    vertex_offset = 0
    for part in parts:
        lines.append(f"o {part['name']}")
        for vertex in part["vertices"]:
            lines.append(f"v {vertex[0]:.3f} {vertex[1]:.3f} {vertex[2]:.3f}")
        for face in part["faces"]:
            lines.append("f " + " ".join(str(vertex_offset + index) for index in face))
        lines.append("")
        vertex_offset += len(part["vertices"])

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parts = build_booth_parts()
    write_obj(OUT_PATH, parts)
    print(f"Written {OUT_PATH}")
    print(f"Components: {len(parts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
