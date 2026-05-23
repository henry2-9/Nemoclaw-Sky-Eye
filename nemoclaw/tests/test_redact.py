import os, sys, tempfile
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import redact

def test_blur_regions_changes_only_bbox():
    # 對均勻色塊做模糊不會改變數值;用「跨邊緣」的 bbox 才測得到效果。
    img = np.full((100, 100, 3), 128, dtype=np.uint8)
    img[50:, :] = 255  # 下半白,在 row 50 形成水平邊緣
    p = os.path.join(tempfile.mkdtemp(), "in.png"); cv2.imwrite(p, img)
    out = redact.blur_regions(p, [(0, 30, 100, 70)])  # bbox 跨越 row 50 邊緣
    res = cv2.imread(out)
    # bbox 內、邊緣上方原 128,被下方白拉高 → 介於兩者之間(已模糊)
    assert 128 < res[48, 50].mean() < 255
    # bbox 外應完全不變
    assert res[10, 10].mean() == 128
    assert res[90, 90].mean() == 255
