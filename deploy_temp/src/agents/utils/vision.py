from PIL import Image
import imagehash
from io import BytesIO

THRESHOLD = 8  # pHash Hamming distance for meaningful change


def phash_bytes(img_bytes: bytes) -> str:
    img = Image.open(BytesIO(img_bytes)).convert('RGB')
    return str(imagehash.phash(img))


def visual_change(h1: str, h2: str) -> int:
    # lower distance = more similar
    return imagehash.hex_to_hash(h1) - imagehash.hex_to_hash(h2)

