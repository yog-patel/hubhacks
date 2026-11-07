"""v2 units: network guard, k-means prototypes, per-species top matches (synthetic data, no models)."""
import socket

import numpy as np
import pytest

from bluesight.identify import top_matches
from bluesight.netguard import NetworkGuard, is_local
from bluesight.registry import compute_prototypes


def unit(v):
    v = np.asarray(v, np.float32)
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


# ------------------------------------------------------------------ network guard
def test_is_local():
    assert is_local("127.0.0.1") and is_local("::1") and is_local("localhost") and is_local(None)
    assert not is_local("huggingface.co") and not is_local("8.8.8.8")


def test_guard_blocks_and_counts_external():
    with NetworkGuard("block") as g:
        with pytest.raises(OSError):
            socket.getaddrinfo("example.com", 443)
        s = socket.socket()
        with pytest.raises(ConnectionRefusedError):
            s.connect(("93.184.216.34", 80))
        s.close()
    assert g.external_attempts == 2 and g.summary()["blocked"] == 2


def test_guard_allows_localhost_and_restores_socket():
    real = socket.socket.connect
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    with NetworkGuard("block") as g:
        c = socket.socket()
        c.connect(srv.getsockname())  # must not raise
        c.close()
    srv.close()
    assert g.external_attempts == 0 and g.local_connections == 1
    assert socket.socket.connect is real


def test_guard_count_mode_records_without_blocking_dns_of_local():
    with NetworkGuard("count") as g:
        socket.getaddrinfo("localhost", 80)
    assert g.external_attempts == 0


# ------------------------------------------------------------------ prototypes
def test_compute_prototypes_small_species_keeps_one_mean():
    e = unit(np.random.default_rng(0).normal(size=(5, 16)))
    P = compute_prototypes(e, k_max=4, min_per_prototype=8)
    assert P.shape == (1, 16)
    assert np.allclose(P[0], unit(e.mean(0)), atol=1e-5)


def test_compute_prototypes_finds_two_modes_deterministically():
    rng = np.random.default_rng(1)
    a, b = unit(rng.normal(size=16)), unit(rng.normal(size=16))
    e = unit(np.r_[a + 0.05 * rng.normal(size=(20, 16)), b + 0.05 * rng.normal(size=(20, 16))])
    P1 = compute_prototypes(e, k_max=2, min_per_prototype=8)
    P2 = compute_prototypes(e, k_max=2, min_per_prototype=8)
    assert P1.shape == (2, 16) and np.allclose(P1, P2)
    assert (P1 @ a).max() > 0.95 and (P1 @ b).max() > 0.95


def test_top_matches_aggregates_sub_prototypes_per_species():
    names = ["cod", "cod", "crab"]
    protos = unit(np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], np.float32))
    top = top_matches(unit([0.1, 0.9, 0.2]), names, protos, 3)
    assert [t["species"] for t in top] == ["cod", "crab"]       # distinct species only
    assert top[0]["similarity"] == pytest.approx(float(unit([0.1, 0.9, 0.2])[1]))
