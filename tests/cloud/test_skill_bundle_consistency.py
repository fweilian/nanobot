from __future__ import annotations

from pathlib import Path

from nanobot.cloud.skills_cache import build_skill_bundle


def _make_skill(root: Path, name: str, body: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")
    (skill_dir / "helper.sh").write_text("echo helper", encoding="utf-8")
    return skill_dir


def test_same_bundle_revision_resolves_same_object_set(tmp_path: Path):
    skill_a = _make_skill(tmp_path / "a", "demo", "# same")
    skill_b = _make_skill(tmp_path / "b", "demo", "# same")

    bundle_a = build_skill_bundle(
        skill_name="demo",
        source_dir=skill_a,
        source_kind="workspace",
        source=skill_a.as_posix(),
        relative_target="skills/demo",
        small_skill_max_bytes=1024,
    ).manifest
    bundle_b = build_skill_bundle(
        skill_name="demo",
        source_dir=skill_b,
        source_kind="workspace",
        source=skill_b.as_posix(),
        relative_target="skills/demo",
        small_skill_max_bytes=1024,
    ).manifest

    assert bundle_a.bundle_revision == bundle_b.bundle_revision
    assert bundle_a.object_list == bundle_b.object_list


def test_bundle_revision_changes_when_skill_contents_change(tmp_path: Path):
    skill_dir = _make_skill(tmp_path, "demo", "# before")
    bundle_before = build_skill_bundle(
        skill_name="demo",
        source_dir=skill_dir,
        source_kind="workspace",
        source=skill_dir.as_posix(),
        relative_target="skills/demo",
        small_skill_max_bytes=1024,
    ).manifest

    (skill_dir / "helper.sh").write_text("echo changed", encoding="utf-8")

    bundle_after = build_skill_bundle(
        skill_name="demo",
        source_dir=skill_dir,
        source_kind="workspace",
        source=skill_dir.as_posix(),
        relative_target="skills/demo",
        small_skill_max_bytes=1024,
    ).manifest

    assert bundle_before.bundle_revision != bundle_after.bundle_revision
