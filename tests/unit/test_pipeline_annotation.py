from accident_vision.pipeline import collision_region


def test_collision_region_wraps_detected_objects_with_padding():
    assert collision_region([[100.5, 80.2, 200.1, 180.8],
                             [190.0, 100.0, 300.0, 220.0]], 640, 360) == (
        93, 73, 307, 227)


def test_collision_region_uses_frame_border_without_objects():
    assert collision_region([], 640, 360) == (2, 2, 637, 357)
