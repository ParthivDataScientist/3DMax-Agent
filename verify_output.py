import json

data = json.load(open("output/complex_scene/analysis/complex_scene_analysis.json", encoding="utf-8"))

print("=== COMPONENTS ===")
for c in data.get("components", []):
    d = c["dimensions"]
    flags = c.get("fabrication", {}).get("flags", [])
    cid = c["id"]
    ctype = c["type"]
    shape = c["shape"]
    orient = c["orientation"]
    src = c.get("source_name", "?")
    print(f"  C{cid:02d} [{ctype:<15s}] shape={shape:<12s} orient={orient:<10s} source={src}")
    print(f"       flags={flags}")
    if d.get("diameter") is not None:
        print(f"       diameter={d['diameter']} mm   radius={d['radius']} mm")
    print()

print("=== BOM ===")
bom = json.load(open("output/complex_scene/bom/bom.json", encoding="utf-8"))
for row in bom:
    pid = row["part_id"]
    ptype = row["type"]
    qty = row["quantity"]
    dia = row.get("diameter_mm")
    src = row.get("source_name", "?")
    review = row.get("manual_review_required", False)
    print(f"  {pid} [{ptype:<15s}] qty={qty}  diameter={dia}  source={src}  review={review}")

print()
print("=== PART GROUPS (source + review check) ===")
for g in data["fabrication"]["part_groups"]:
    pgid = g["part_group_id"]
    otype = g["object_type"]
    src = g.get("source_name", "MISSING")
    review = g.get("manual_review_required", "MISSING")
    shape = g.get("shape", "MISSING")
    print(f"  {pgid} [{otype:<15s}] source={src}  review={review}  shape={shape}")
