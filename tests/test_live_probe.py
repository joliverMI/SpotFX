"""The pure parts of scripts/preview_perf/live_probe.py (the read-only
live measurement behind data/preview-p4-live-check/report.md): the `ss`
info parser, the percentile, the proxy-hop subtraction and the viewer
summary. The live halves (sockets, HTTP, the stream) are not driven here —
no live access from tests, ever."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "live_probe", REPO / "scripts" / "preview_perf" / "live_probe.py")
live_probe = importlib.util.module_from_spec(spec)
sys.modules["live_probe"] = live_probe
spec.loader.exec_module(live_probe)


def test_parse_ss_info_reads_the_fields_the_report_uses():
    info = ("\t cubic wscale:7,10 rto:212 rtt:11.421/9.956 ato:40 mss:1448 cwnd:10 "
            "bytes_sent:146920 bytes_retrans:71 bytes_acked:146849 unacked:1 "
            "notsent:1448 busy:270743ms retrans:0/8 minrtt:1.776 snd_wnd:63232")
    d = live_probe.parse_ss_info(info)
    assert d["rtt_ms"] == 11.421 and d["rtt_var_ms"] == 9.956
    assert d["retrans_now"] == 0 and d["retrans_total"] == 8
    assert d["minrtt"] == 1.776 and d["unacked"] == 1 and d["notsent"] == 1448
    assert d["bytes_sent"] == 146920 and d["bytes_retrans"] == 71
    assert d["busy"] == 270743


def test_parse_ss_info_without_retrans_or_rtt_is_empty_not_wrong():
    assert live_probe.parse_ss_info("\t cubic wscale:7,10") == {}


def test_tailscale_peer_matches_only_the_cgnat_range():
    assert live_probe.TAILSCALE_RE.match("100.92.91.38")
    assert live_probe.TAILSCALE_RE.match("100.127.0.1")
    assert not live_probe.TAILSCALE_RE.match("100.128.0.1")
    assert not live_probe.TAILSCALE_RE.match("192.168.40.16")
    assert not live_probe.TAILSCALE_RE.match("127.0.0.1")


def test_percentile_is_linear_between_samples():
    assert live_probe.percentile([], 0.5) is None
    assert live_probe.percentile([1.0, 3.0], 0.5) == 2.0
    assert live_probe.percentile([1.0, 2.0, 10.0], 0.95) == 9.2


def _viewer(name, delays, arrivals, seqs, rates):
    rec = live_probe.ViewerRecord(name, "ws://x")
    rec.delays_ms = list(delays)
    rec.arrivals = list(arrivals)
    rec.seqs = list(seqs)
    rec.rates = list(rates)
    rec.ages_ms = [0] * len(delays)
    rec.srtts_ms = [0] * len(delays)
    rec.messages = len(delays)
    rec.bytes = 1000 * len(delays)
    return rec


def test_hop_summary_is_proxied_minus_direct_at_matched_percentiles():
    proxied = _viewer("p", [10, 20, 30, 40, 1000], range(5), range(5), [30] * 5)
    direct = _viewer("d", [1, 2, 3, 4, 5], range(5), range(5), [30] * 5)
    hop = live_probe.hop_summary(proxied, direct)
    assert hop["p50"] == 27.0
    assert hop["p99"] > hop["p95"] > hop["p50"]


def test_viewer_summary_counts_gaps_seq_holes_and_rate_share():
    arrivals = [0.0, 0.033, 0.066, 0.3, 0.333]       # one gap of 234 ms
    rec = _viewer("v", [1, 1, 1, 1, 1], arrivals, [1, 2, 4, 5, 6], [30, 30, 20, 20, 20])
    s = rec.summary()
    assert s["interval_ms"]["gaps_over_100ms"] == 1
    assert s["seq_gaps"] == 1
    assert s["rate_fps_share"] == {"20": 0.6, "30": 0.4}
    assert s["delivered_fps"] == round(5 / 0.333, 2)
    assert s["kbit_s"] == round(5000 * 8 / 0.333 / 1000, 1)


def test_render_md_lists_every_viewer_including_extras():
    r = {"started": "t", "duration_s": 1, "level": "full", "scope": "favorites",
         "playing_share": 1.0,
         "viewers": {k: _viewer(k, [1.0], [0.0], [1], [30]).summary()
                     for k in ("proxy", "direct", "serve")},
         "proxy_hop_ms": {"p50": 0.0, "p95": 0.0, "p99": 0.0},
         "his_sockets": {}, "liveness_ms": {"8000": {"samples": 0, "p50": None, "p95": None,
                                                     "max": None, "errors": 0}}}
    md = live_probe.render_md(r)
    assert "| serve |" in md and "| proxy |" in md and "| direct |" in md
