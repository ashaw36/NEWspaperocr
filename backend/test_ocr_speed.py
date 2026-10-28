#!/usr/bin/env python
"""Test actual OCR speed"""
import os
import sys
import time
from pathlib import Path

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

from paddleocr import PaddleOCR

test_image = r"D:\古报纸OCR\backend\uploads\20260918_160008_page_001.png"

if not Path(test_image).exists():
    print(f"ERROR: Image not found: {test_image}")
    sys.exit(1)

print("Initializing PaddleOCR...")
start_init = time.time()
ocr = PaddleOCR(lang='ch', ocr_version='PP-OCRv5')
init_time = time.time() - start_init
print(f"Initialization: {init_time:.1f}s\n")

print(f"Testing: {test_image}")
print("Running OCR...")
start_ocr = time.time()
result = ocr.ocr(test_image, cls=False)
ocr_time = time.time() - start_ocr

print(f"\n✅ OCR completed in {ocr_time:.1f}s")
print(f"Total time: {init_time + ocr_time:.1f}s")

if result and result[0]:
    print(f"\nRecognized {len(result[0])} text blocks")
    print(f"\nFirst 3 blocks:")
    for i, item in enumerate(result[0][:3], 1):
        bbox, (text, conf) = item
        print(f"  {i}. {text[:30]}... (conf: {conf:.2f})")
else:
    print("\n⚠️  No text recognized")
