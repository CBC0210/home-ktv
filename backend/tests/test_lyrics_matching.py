"""Candidate-verification scoring for lyric sources.

Every (query, candidate) pair below was captured from LIVE QQ / NetEase
search responses on 2026-07-18 while diagnosing the「字幕是別首歌」reports:
the ACCEPT cases are the correct catalog entries, the REJECT cases are the
wrong songs the old blind-first-hit code actually served to users.
"""
import pytest

from ktv_pipeline.pipeline.lyrics import (
    _ACCEPT_SCORE,
    _score_candidate,
    _title_sim,
    clean_song_query,
)


def score(q_title, q_artist, c_title, c_artist, dur, cand_dur):
    return _score_candidate(
        q_title, q_artist, c_title, c_artist,
        duration_sec=dur, cand_duration_sec=cand_dur,
    )


class TestAcceptsCorrectMatches:
    def test_simplified_with_alt_title(self):
        # 妥協 Compromise → QQ '妥协' (Δ2s). Old scorer gave this 0.17.
        assert score("妥協 Compromise", "JOLIN 蔡依林", "妥协", "蔡依林", 262, 264) >= _ACCEPT_SCORE

    def test_artist_inside_video_title_channel_uploader(self):
        # Uploader is the label channel; the artist lives in the title.
        # Old NetEase scorer REJECTED this correct match.
        assert score(
            "MAYDAY五月天 派對動物Party Animal", "相信音樂BinMusic",
            "派对动物", "五月天", 284, 249,
        ) >= _ACCEPT_SCORE

    def test_romanized_title_rescued_by_artist_and_duration(self):
        # Latin query vs Japanese catalog title — zero text overlap; exact
        # artist + Δ1s duration must identify it.
        assert score(
            "Marunouchi Sadistic", "椎名林檎",
            "丸ノ内サディスティック (丸内虐待狂)", "椎名林檎 (しいな りんご)",
            236, 235,
        ) >= _ACCEPT_SCORE

    def test_garbage_cleaned_title_rescued_by_artist_and_duration(self):
        # clean_song_query picked the noise side of the dash; artist+duration
        # still identify the right song.
        assert score(
            "電影「月老」主題曲導演親剪音樂視角版", "韋禮安 WeiBird",
            "如果可以", "韦礼安", 275, 274,
        ) >= _ACCEPT_SCORE

    def test_cjk_core_equality_through_mixed_scripts(self):
        assert score(
            "小紫aka給我錢 Money Money", "芒果醬Mango Jump",
            "小紫aka给我钱", "芒果酱 Mango Jump", 260, 250,
        ) >= _ACCEPT_SCORE


class TestRejectsWrongMatches:
    def test_meme_video_random_hit(self):
        # QQ result #0 for the meme video — a stranger's clip, Δ200s.
        assert score(
            "十月表，但是啊啊啊啊啊啊啊啊啊", "ALise",
            "啊啊啊啊啊啊啊啊啊啊啊啊啊玩玩看~【滚", "漆柚", 249, 49,
        ) < _ACCEPT_SCORE

    def test_unrelated_popular_song(self):
        # 崴孟三百天禮物 → QQ served 錯過/梁咏琪.
        assert score("崴孟三百天禮物", "崴崴孟孟 - Topic", "错过", "梁咏琪", 236, 268) < _ACCEPT_SCORE

    def test_bgm_track_matched_to_real_song(self):
        assert score(
            "稻荷恋之歌 BGM InaKon BGM 2", "KB Sotong",
            "夏祭り、夢花火。", "妹尾武", 121, 243,
        ) < _ACCEPT_SCORE

    def test_same_artist_different_song(self):
        # The sneakiest failure: correct artist, wrong song (Δ55s).
        assert score(
            "小紫aka給我錢 Money Money", "芒果醬Mango Jump",
            "夏夜晚风", "芒果酱 Mango Jump", 260, 205,
        ) < _ACCEPT_SCORE

    def test_franchise_character_not_artist(self):
        # 初音ミク in the title must NOT count as an artist match for 初音未来
        # singing a different song.
        assert score(
            "初音ミク / Hatsune Miku / ヒトリトラベル", "Devend Conor",
            "红楼月", "初音未来", 247, 194,
        ) < _ACCEPT_SCORE


class TestScoreOrdering:
    def test_correct_match_outscores_cover_with_wrong_duration(self):
        # 妥协 by 蔡依林 (Δ2s) must beat 妥协 by a cover artist (Δ81s).
        right = score("妥協 Compromise", "JOLIN 蔡依林", "妥协", "蔡依林", 262, 264)
        cover = score("妥協 Compromise", "JOLIN 蔡依林", "妥协", "Diwen L.l", 262, 181)
        assert right > cover
        assert cover < _ACCEPT_SCORE

    def test_title_sim_handles_traditional_simplified(self):
        assert _title_sim("妥協 Compromise", "妥协") == 1.0

    def test_clean_song_query_strips_mv_noise(self):
        t, a = clean_song_query(
            "蔡依林 Jolin Tsai - 妥協 Compromise (華納official 官方完整版MV)",
            "JOLIN 蔡依林",
        )
        assert "妥協" in t
        assert "MV" not in t
