from __future__ import annotations

from pathlib import Path

from nanobot.cloud.skills_cache import build_skill_bundle


def test_build_skill_bundle_records_immutable_descriptor(tmp_path: Path):
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# test", encoding="utf-8")
    (skill_dir / "script.sh").write_text("echo hi", encoding="utf-8")

    bundle = build_skill_bundle(
        skill_name="demo",
        source_dir=skill_dir,
        source_kind="workspace",
        source=skill_dir.as_posix(),
        relative_target="skills/demo",
        small_skill_max_bytes=1024,
    )

    manifest = bundle.manifest
    assert manifest.skill_name == "demo"
    assert manifest.bundle_revision == manifest.bundle_hash
    assert manifest.object_list == ["SKILL.md", "script.sh"]
    assert manifest.total_bytes > 0
    assert manifest.relative_target == "skills/demo"
    assert manifest.small_content_eligible is True
