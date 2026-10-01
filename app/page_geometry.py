"""Conservative paper extraction for photographs, before handwriting removal."""

import cv2
import numpy as np
from PIL import Image


def rectify_page_photo(image: Image.Image) -> Image.Image | None:
    """Return a rectified page only when a large, bright paper outline is clear.

    The mask is filled from the outer contour, so printed strokes and diagrams
    inside the paper are not treated as holes to erase.
    """
    if min(image.size) < 360:
        return None
    rgb = np.asarray(image.convert("RGB"))
    scale = min(1.0, 1000 / max(image.size))
    small = cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(contour)
    height, width = gray.shape
    if not 0.55 <= area / (width * height) <= 0.98:
        return None

    paper_mask = np.zeros_like(mask)
    cv2.drawContours(paper_mask, [contour], -1, 255, cv2.FILLED)
    inside, outside = gray[paper_mask != 0], gray[paper_mask == 0]
    if not len(outside) or np.percentile(inside, 60) - np.percentile(outside, 60) < 35:
        return None

    perimeter = cv2.arcLength(contour, True)
    quad = None
    for tolerance in (0.01, 0.015, 0.02):
        candidate = cv2.approxPolyDP(contour, tolerance * perimeter, True)
        if len(candidate) == 4 and cv2.isContourConvex(candidate):
            if abs(cv2.contourArea(candidate) - area) / area <= 0.04:
                quad = candidate[:, 0].astype(np.float32)
                break
    if quad is None:
        return None

    # Top-left, top-right, bottom-right, bottom-left. Reject ambiguous ordering.
    sums, differences = quad.sum(axis=1), quad[:, 0] - quad[:, 1]
    order = [int(sums.argmin()), int(differences.argmax()), int(sums.argmax()), int(differences.argmin())]
    if len(set(order)) != 4:
        return None
    quad = quad[order]
    quad *= np.array([image.width / width, image.height / height], dtype=np.float32)
    tl, tr, br, bl = quad
    output_width = round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    output_height = round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    if output_width < image.width * 0.5 or output_height < image.height * 0.5:
        return None
    if not 0.35 <= output_width / output_height <= 3.0:
        return None

    destination = np.float32([[0, 0], [output_width - 1, 0], [output_width - 1, output_height - 1], [0, output_height - 1]])
    transform = cv2.getPerspectiveTransform(quad, destination)
    result = cv2.warpPerspective(rgb, transform, (output_width, output_height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
    full_mask = cv2.resize(paper_mask, image.size, interpolation=cv2.INTER_NEAREST)
    full_mask = cv2.warpPerspective(full_mask, transform, (output_width, output_height), flags=cv2.INTER_NEAREST)
    result[full_mask == 0] = 255
    return Image.fromarray(result)
