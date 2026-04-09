import json
from pathlib import Path

models = ["flat_plate", "box", "cylinder", "sphere", "exhibition_fabrication_test", "complex_scene"]

all_passed = True
print(f"{'MODEL':<35} {'EXIT':<6} {'PARTS':<6} {'REVIEWS'}")
print("-" * 75)

for model in models:
    bom_path = Path(f"output/{model}/bom/bom.json")
    analysis_path = Path(f"output/{model}/analysis/{model}_analysis.json")

    if not bom_path.exists() or not analysis_path.exists():
        print(f"{model:<35} MISSING FILES")
        all_passed = False
        continue

    bom = json.loads(bom_path.read_text(encoding="utf-8"))
    data = json.loads(analysis_path.read_text(encoding="utf-8"))

    # Check source_name never None in bom
    source_none = [r for r in bom if r.get("source_name") in (None, "")]
    # Check review flag present and is bool
    review_invalid = [r for r in bom if not isinstance(r.get("manual_review_required"), bool)]
    # Parts that need review
    review_parts = [r["part_id"] for r in bom if r.get("manual_review_required")]
    # Diameter populated for cylinder shapes
    cyl_no_dia = [r for r in bom if r.get("type") in ("pole", "cylinder_part") and r.get("diameter_mm") is None]

    component_count = data.get("component_summary", {}).get("component_count", "?")
    issues = []
    if source_none:        issues.append(f"source_name=None in {len(source_none)} rows")
    if review_invalid:     issues.append(f"review field invalid in {len(review_invalid)} rows")
    if cyl_no_dia:         issues.append(f"cylinder missing diameter in {len(cyl_no_dia)} rows")

    status = "PASS" if not issues else "FAIL"
    if issues:
        all_passed = False
    review_str = str(review_parts) if review_parts else "none"
    print(f"{model:<35} {status:<6} {len(bom):<6} reviews={review_str}")
    for issue in issues:
        print(f"  !! {issue}")

    # Print angled panel flags
    for c in data.get("components", []):
        flags = c.get("fabrication", {}).get("flags", [])
        if "angled_panel" in flags:
            tilt = next((f for f in flags if f.startswith("tilt_")), "?")
            print(f"  >> C{c['id']:02d} angled panel detected: {tilt}")

print()
print("=" * 75)
print("OVERALL:", "ALL PASS" if all_passed else "SOME FAILURES")
