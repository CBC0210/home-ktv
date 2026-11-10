"""Tests for the shared local/YouTube song-search filter."""
import pytest

from ktv_pipeline.search_filter import is_song_search_result


@pytest.mark.parametrize(
    ("title", "duration", "expected"),
    [
        ("周杰倫 - 晴天 Official MV", 269, True),
        ("五月天【知足】完整版 Official Live Video", 285, True),
        ("張學友 經典金曲（官方MV）", 290, True),
        ("送給酸民的一首歌!? Official MV", 190, True),
        ("最近很火的1首歌《天際》", 350, True),
        ("周杰倫 20首歌曲精選集", 540, False),
        ("周杰倫 二十首歌曲精選集", 540, False),
        ("80年代金曲串燒", 420, False),
        ("Best 10 Songs Collection", 510, False),
        ("DJ Medley 2026", 360, False),
        ("Dance Compilation", 360, False),
        ("歌手完整專輯 Full Album", 480, False),
        ("歌手訪談：新歌創作", 300, False),
    ],
)
def test_title_and_duration_filter(title, duration, expected):
    assert is_song_search_result(
        {"title": title, "duration": duration}, 60, 600
    ) is expected


@pytest.mark.parametrize(
    "entry",
    [
        {"title": "短預告", "duration": 59},
        {"title": "長篇演唱會", "duration": 601},
        {"title": "直播", "duration": None},
        {"title": "直播", "duration": True},
        {"title": "無限長", "duration": float("inf")},
    ],
)
def test_duration_must_be_a_numeric_song_length(entry):
    assert is_song_search_result(entry, 60, 600) is False


def test_local_song_duration_key_is_supported():
    assert is_song_search_result(
        {"title": "告白氣球 Official MV", "duration_sec": 216}, 60, 600
    ) is True


@pytest.mark.parametrize(
    "entry",
    [
        {"title": "短直播", "duration": 120, "is_live": True},
        {"title": "直播預告", "duration": 120, "live_status": "is_upcoming"},
    ],
)
def test_live_results_are_rejected_even_with_a_song_length(entry):
    assert is_song_search_result(entry, 60, 600) is False
