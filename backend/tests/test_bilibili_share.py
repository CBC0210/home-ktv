from email.message import Message
from urllib.error import HTTPError

import pytest

from ktv_pipeline.bilibili_share import (
    BilibiliShareError,
    extract_bilibili_url,
    extract_bilibili_video_id,
    resolve_bilibili_short_link,
)


def _redirect(url: str, location: str) -> HTTPError:
    headers = Message()
    headers["Location"] = location
    return HTTPError(url, 302, "Found", headers, None)


def test_extracts_url_from_bilibili_app_share_text():
    assert extract_bilibili_url("【短歌】 https://b23.tv/abc123 請打開") == "https://b23.tv/abc123"
    assert extract_bilibili_url("https://www.bilibili.com/video/BV1xx411c7mD") == "https://www.bilibili.com/video/BV1xx411c7mD"


def test_short_link_validates_every_redirect_hop():
    requests = []

    def open_request(request, timeout):
        requests.append(request.full_url)
        if request.full_url == "https://b23.tv/abc":
            raise _redirect(request.full_url, "https://www.bilibili.com/video/BV1xx411c7mD")
        raise AssertionError("已到達影片 URL，不應再抓取影片頁")

    assert resolve_bilibili_short_link("https://b23.tv/abc", open_request=open_request) == "https://www.bilibili.com/video/BV1xx411c7mD"
    assert requests == ["https://b23.tv/abc"]


def test_short_link_rejects_unknown_redirect_before_requesting_it():
    def open_request(request, timeout):
        raise _redirect(request.full_url, "http://127.0.0.1:8000/private")

    with pytest.raises(BilibiliShareError, match="不允許的網域"):
        resolve_bilibili_short_link("https://b23.tv/abc", open_request=open_request)


def test_rejects_http_and_excessive_redirects():
    with pytest.raises(BilibiliShareError, match="HTTPS"):
        resolve_bilibili_short_link("http://b23.tv/abc")

    def open_request(request, timeout):
        raise _redirect(request.full_url, "https://b23.tv/again")

    with pytest.raises(BilibiliShareError, match="次數過多"):
        resolve_bilibili_short_link("https://b23.tv/abc", open_request=open_request)


@pytest.mark.parametrize(
    "url",
    [
        "https://user@b23.tv/abc",
        "https://b23.tv:444/abc",
        "https:///abc",
    ],
)
def test_short_link_rejects_credentials_nonstandard_port_and_missing_host(url):
    with pytest.raises(BilibiliShareError):
        resolve_bilibili_short_link(url)


def test_direct_bilibili_multi_part_is_explicitly_rejected():
    with pytest.raises(BilibiliShareError, match="多 P"):
        extract_bilibili_video_id("【歌】https://www.bilibili.com/video/BV1xx411c7mD?p=2")


class _Response:
    def __init__(self, url):
        self.url = url

    def geturl(self):
        return self.url

    def close(self):
        pass
