"""Tests for the batch rename feature in photo_s.rename."""

import os
import sys

# Ensure src package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from photo_s.rename import rename_files, _unique_target


def _make_images(tmp_path, count=3, fmt="PNG"):
    paths = []
    for i in range(count):
        p = tmp_path / f"IMG_{i:04d}.{fmt.lower()}"
        Image.new("RGB", (20, 20), (i * 50, 100, 200)).save(p)
        paths.append(str(p))
    return paths


class TestRenameInPlace:
    def test_basic_rename(self, tmp_path):
        paths = _make_images(tmp_path)
        results = rename_files(paths, "Trip_{seq}")
        assert all(r["status"] == "ok" for r in results)
        names = sorted(p.name for p in tmp_path.iterdir())
        assert names == ["Trip_001.png", "Trip_002.png", "Trip_003.png"]

    def test_original_placeholder_is_stem(self, tmp_path):
        paths = _make_images(tmp_path)
        results = rename_files(paths, "{original}_x")
        ok = [r for r in results if r["status"] == "ok"]
        assert len(ok) == 3
        # files are also renamed among each other; check a known mapping
        for r in results:
            assert r["status"] == "ok"
        assert ok[0]["output"].endswith("IMG_0000_x.png")

    def test_unknown_placeholder_preserved(self, tmp_path):
        paths = _make_images(tmp_path)
        results = rename_files(paths, "{foo}_{seq}")
        assert results[0]["status"] == "ok"
        assert os.path.basename(results[0]["output"]).startswith("{foo}_")


class TestRenameToOutputDir:
    def test_copies_and_keeps_originals(self, tmp_path):
        paths = _make_images(tmp_path)
        out_dir = tmp_path / "renamed"
        results = rename_files(paths, "Trip_{seq}", output_dir=str(out_dir))
        assert all(r["status"] == "ok" for r in results)
        # originals still exist
        assert len([p for p in tmp_path.iterdir() if p.suffix == ".png"]) == 3
        # copies in output dir with new names
        assert sorted(p.name for p in out_dir.iterdir()) == \
            ["Trip_001.png", "Trip_002.png", "Trip_003.png"]


class TestRenameEscape:
    """A crafted EXIF Make/DateTime must never escape the output dir."""

    def _crafted_jpeg(self, tmp_path, make=b"../../evil"):
        import piexif
        from PIL import Image
        exif_dict = {
            "0th": {piexif.ImageIFD.Make: make},
            "Exif": {},
            "GPS": {}, "1st": {}, "thumbnail": None,
        }
        p = tmp_path / "photo.jpg"
        Image.new("RGB", (8, 8)).save(p, quality=90, exif=piexif.dump(exif_dict))
        return str(p)

    def test_escaped_make_stays_in_outdir(self, tmp_path):
        src = self._crafted_jpeg(tmp_path, make=b"../../evil")
        out_dir = tmp_path / "out"
        results = rename_files([src], "{make}_{original}",
                               output_dir=str(out_dir))
        assert results[0]["status"] == "ok"
        # output must be inside out_dir, never "../.."
        out = os.path.abspath(results[0]["output"])
        assert out.startswith(os.path.abspath(str(out_dir)) + os.sep)
        assert ".." not in os.path.basename(out)
        assert (out_dir / "evil_photo.jpg").exists()

    def test_unsafe_render_is_error(self, tmp_path):
        # Literal separators from the operator's own pattern aren't an attack,
        # but the guard must refuse them rather than escape the directory
        src = tmp_path / "a.png"
        Image.new("RGB", (8, 8)).save(src)
        results = rename_files([str(src)], "../escape_{seq}",
                               output_dir=str(tmp_path / "out"))
        assert results[0]["status"] == "error"
        assert not (tmp_path / "escape_001.png").exists()


class TestDryRun:
    def test_no_files_changed(self, tmp_path):
        paths = _make_images(tmp_path)
        results = rename_files(paths, "Trip_{seq}", dry_run=True)
        assert all(r["status"] == "ok" for r in results)
        # nothing renamed on disk
        names = sorted(p.name for p in tmp_path.iterdir())
        assert names == [f"IMG_{i:04d}.png" for i in range(3)]


class TestCollision:
    def test_unique_target_appends_number(self, tmp_path):
        target = str(tmp_path / "a.png")
        Image.new("RGB", (10, 10)).save(target)
        assert _unique_target(target, overwrite=False).endswith("a_1.png")
        # overwrite allows clobber
        assert _unique_target(target, overwrite=True) == target

    def test_unique_target_clean_counter_on_original_stem(self, tmp_path):
        # regression: a.png AND a_1.png both exist → next is a_2.png,
        # not a_1_2.png (the old re-suffix-the-suffixed-stem bug)
        for name in ("a.png", "a_1.png"):
            Image.new("RGB", (5, 5)).save(tmp_path / name)
        got = _unique_target(str(tmp_path / "a.png"), overwrite=False)
        assert got == str(tmp_path / "a_2.png")
        # and it keeps counting cleanly for a third collision
        Image.new("RGB", (5, 5)).save(tmp_path / "a_2.png")
        got2 = _unique_target(str(tmp_path / "a.png"), overwrite=False)
        assert got2 == str(tmp_path / "a_3.png")

    def test_seq_collision_avoids_overwrite(self, tmp_path):
        # two files, same pattern → collision, second gets _1
        paths = _make_images(tmp_path, count=2)
        # pre-create the exact target of the first file so it must dedupe
        pre = tmp_path / "Same_001.png"
        Image.new("RGB", (5, 5)).save(pre)
        results = rename_files(paths, "Same_{seq}")
        assert all(r["status"] == "ok" for r in results)
        assert os.path.basename(results[0]["output"]) == "Same_001_1.png"

    def test_overwrite_replaces_existing_target(self, tmp_path):
        # Regression: in-place rename used os.rename, which raises
        # FileExistsError on Windows when the target exists — making
        # --overwrite useless there. os.replace clobbers on every OS.
        src = tmp_path / "a.png"
        Image.new("RGB", (8, 8), (1, 2, 3)).save(src)
        target = tmp_path / "b.png"
        Image.new("RGB", (8, 8), (9, 9, 9)).save(target)
        results = rename_files([str(src)], "b", overwrite=True)
        assert results[0]["status"] == "ok"
        assert results[0]["output"] == str(target)
        assert not src.exists()
        with Image.open(target) as img:
            assert img.getpixel((0, 0)) == (1, 2, 3)  # target has src content


class TestEmptyRenderFallback:
    """Regression: a pure-EXIF template ({date}, {year}{month}{day}) on a
    file without EXIF rendered an empty stem → hidden ".png"/".png_1"
    files reported as ok. The stem must fall back to the original name."""

    def test_empty_render_falls_back_to_original(self, tmp_path):
        paths = _make_images(tmp_path, count=2)  # PNGs carry no EXIF dates
        out_dir = tmp_path / "out"
        results = rename_files(paths, "{date}", output_dir=str(out_dir))
        assert all(r["status"] == "ok" for r in results)
        names = sorted(p.name for p in out_dir.iterdir())
        assert names == ["IMG_0000.png", "IMG_0001.png"]

    def test_empty_render_in_place_makes_no_hidden_file(self, tmp_path):
        paths = _make_images(tmp_path, count=1)
        results = rename_files(paths, "{year}{month}{day}")
        assert results[0]["status"] == "ok"
        names = [p.name for p in tmp_path.iterdir()]
        # exactly one visible file remains; no ".png"-style hidden output
        assert len(names) == 1
        assert not any(n.startswith(".") for n in names)
