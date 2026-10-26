import io

import numpy as np
from PIL import Image

from panorama360.postprocess import clean_poles, fit_equirect, gpano_xmp, insert_xmp, save_panorama
from panorama360.projection import photo_to_equirect


def _noise(width=256):
    rng = np.random.default_rng(0)
    return Image.fromarray(rng.integers(0, 255, (width // 2, width, 3), dtype=np.uint8))


def test_saved_jpeg_carries_gpano_metadata(tmp_path):
    path = save_panorama(_noise(), tmp_path / "p.jpg", metadata={"seed": 1})
    data = path.read_bytes()
    assert data[:2] == b"\xff\xd8"
    assert b'GPano:ProjectionType="equirectangular"' in data
    assert b'GPano:FullPanoWidthPixels="256"' in data
    with Image.open(path) as image:
        image.load()
        assert image.size == (256, 128)
        assert "equirectangular" in str(image.info.get("xmp", b""))
    assert (tmp_path / "p.json").exists()


def test_xmp_goes_after_jfif_header():
    buffer = io.BytesIO()
    _noise(64).save(buffer, format="JPEG")
    patched = insert_xmp(buffer.getvalue(), gpano_xmp(64, 32))
    assert patched[2:4] == b"\xff\xe0"  # APP0 JFIF primero
    app0_len = int.from_bytes(patched[4:6], "big")
    assert patched[4 + app0_len : 6 + app0_len] == b"\xff\xe1"


def test_clean_poles_flattens_the_top_row_and_keeps_the_equator():
    image = _noise(512)
    cleaned = np.asarray(clean_poles(image), dtype=np.float32)
    original = np.asarray(image, dtype=np.float32)
    assert cleaned[0].std(axis=0).max() < 10  # el cenit queda casi uniforme
    assert original[0].std(axis=0).min() > 50
    middle = slice(100, 156)
    assert np.array_equal(cleaned[middle], original[middle])


def test_fit_equirect_forces_two_to_one():
    assert fit_equirect(Image.new("RGB", (300, 200)), 1000).size == (992, 496)


def test_photo_projection_places_photo_in_front():
    photo = Image.new("RGB", (400, 300), (200, 30, 30))
    pano, mask = photo_to_equirect(photo, 512, fov_degrees=90)
    assert pano.size == (512, 256) and mask.size == (512, 256)
    assert pano.getpixel((256, 128))[0] > 180  # centro = foto
    assert mask.getpixel((256, 128)) < 10  # se conserva
    assert mask.getpixel((5, 128)) > 245  # detrás se inventa
    assert mask.getpixel((256, 2)) > 245  # cenit se inventa
