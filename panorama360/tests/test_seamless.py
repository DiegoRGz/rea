import torch
import torch.nn.functional as F
from torch import nn

from panorama360.seamless import seamless, set_seamless, tile_starts, tiled_apply


def test_identity_tiling_is_exact_with_and_without_wrap():
    x = torch.randn(1, 3, 40, 100)
    for wrap in (True, False):
        out = tiled_apply(x, lambda p: p, scale=1, tile=32, overlap=8, wrap_x=wrap)
        assert torch.allclose(out, x, atol=1e-5)


def test_scaled_tiling_matches_full_upsample():
    x = torch.randn(1, 3, 24, 64)
    up = lambda p: F.interpolate(p, scale_factor=4, mode="nearest")
    out = tiled_apply(x, up, scale=4, tile=16, overlap=4, wrap_x=True)
    assert torch.allclose(out, up(x), atol=1e-5)


def test_downscaled_tiling_aligns_to_blocks():
    x = torch.randn(1, 3, 64, 192)
    down = lambda p: F.avg_pool2d(p, 8)
    out = tiled_apply(x, down, scale=1 / 8, tile=64, overlap=16, align=8, wrap_x=True)
    assert out.shape == (1, 3, 8, 24)
    assert torch.allclose(out, down(x), atol=1e-5)


def test_wrap_always_uses_two_tiles_that_cover_everything():
    starts, tile = tile_starts(96, 128, 16, 1, wrap=True)
    assert len(starts) >= 2 and tile < 96
    covered = set()
    for s in starts:
        covered.update((s + i) % 96 for i in range(tile))
    assert covered == set(range(96))


def _conv():
    torch.manual_seed(0)
    return nn.Conv2d(3, 3, 5, padding=2)


def test_seamless_conv_is_equivariant_to_horizontal_rotation():
    conv = _conv()
    x = torch.randn(1, 3, 16, 48)
    with seamless([conv], True):
        a = conv(torch.roll(x, 7, dims=3))
        b = torch.roll(conv(x), 7, dims=3)
    assert torch.allclose(a, b, atol=1e-5)
    # Al salir del contexto vuelve al relleno con ceros original.
    assert torch.allclose(conv(x), F.conv2d(x, conv.weight, conv.bias, padding=2), atol=1e-6)


def test_seamless_keeps_zero_padding_vertically():
    conv = _conv()
    x = torch.randn(1, 3, 16, 48)
    set_seamless(conv, True)
    expected = F.conv2d(F.pad(F.pad(x, (2, 2, 0, 0), mode="circular"), (0, 0, 2, 2)), conv.weight, conv.bias)
    assert torch.allclose(conv(x), expected, atol=1e-5)
    set_seamless(conv, False)


def test_wrapped_tiles_approach_circular_result_at_the_seam():
    conv = _conv()
    x = torch.randn(1, 3, 32, 128)
    with torch.no_grad():
        with seamless([conv], True):
            reference = conv(x)
        wrapped = tiled_apply(x, conv, scale=1, tile=48, overlap=16, wrap_x=True)
        unwrapped = tiled_apply(x, conv, scale=1, tile=48, overlap=16, wrap_x=False)
    seam = lambda t: torch.cat([t[..., :2], t[..., -2:]], dim=-1)
    assert (seam(wrapped) - seam(reference)).abs().max() < 1e-4
    assert (seam(unwrapped) - seam(reference)).abs().max() > 1e-2
