#!/usr/bin/python3
"""Recolour the Trencher marks: deep purple -> foreground blue, pale -> background blue.

Each pixel is expressed as a mixture of the two purples and white
(c = a*DARK + b*LIGHT + w*WHITE, a+b+w=1) and re-rendered with the new anchors,
so antialiased edges keep their gradations instead of leaving a halo.
"""
import os

import numpy as np
from PIL import Image

IMG = os.path.expanduser("~/Trencher/images")
DARK = np.array([0x60, 0x01, 0x80], float)
LIGHT = np.array([0x6a, 0x3d, 0xe8], float)
WHITE = np.array([255.0, 255.0, 255.0])

DARK_NEW = np.array([0x05, 0x1b, 0xf8], float)   # foreground.png, 12 deg bluer
LIGHT_NEW = np.array([0x6d, 0xad, 0xf8], float)  # background.png, 12 deg bluer

basis = np.column_stack([DARK, LIGHT, WHITE])
pinv = np.linalg.pinv(basis)


def recolour(name, out_name=None):
    src = os.path.join(IMG, name)
    im = Image.open(src).convert("RGBA")
    arr = np.asarray(im).astype(float)
    rgb, alpha = arr[..., :3], arr[..., 3]

    weights = rgb.reshape(-1, 3) @ pinv.T          # (a, b, w) per pixel
    # reconstruct before clamping, to report how well the mixture model fits
    fit = weights @ basis.T
    residual = np.abs(fit - rgb.reshape(-1, 3)).max()

    weights = np.clip(weights, 0, 1)
    total = weights.sum(axis=1, keepdims=True)
    total[total == 0] = 1.0
    weights = weights / total

    new_rgb = weights @ np.column_stack([DARK_NEW, LIGHT_NEW, WHITE]).T
    new_rgb = np.clip(new_rgb, 0, 255).reshape(rgb.shape)

    out = np.dstack([new_rgb, alpha]).astype(np.uint8)
    target = os.path.join(IMG, out_name or name)
    Image.fromarray(out, "RGBA").save(target, optimize=True)
    print(f"{name:22s} -> {os.path.basename(target):22s} max fit error {residual:5.1f}")
    return target


recolour("Trencher.png")
recolour("Trencher_avatar.png")

# the header banner: the avatar drawn at 330x132, as the window will show it
avatar = Image.open(os.path.join(IMG, "Trencher_avatar.png")).convert("RGBA")
banner = avatar.resize((330, 132), Image.LANCZOS)
banner.save(os.path.join(IMG, "banner.png"), optimize=True)
print("banner.png", banner.size)
