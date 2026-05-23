import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import feed

def test_playhead_wraps_around_duration():
    # duration=10, start=0, now=23 → 23 % 10 = 3
    assert feed.playhead(10.0, now=23.0, start=0.0) == 3.0

def test_playhead_zero_duration_safe():
    assert feed.playhead(0.0, now=5.0, start=0.0) == 0.0

def test_playhead_with_start_offset():
    assert feed.playhead(10.0, now=105.0, start=100.0) == 5.0
