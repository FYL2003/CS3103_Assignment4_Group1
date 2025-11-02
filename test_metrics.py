#!/usr/bin/env python3
"""
Test script to verify metrics calculation abstraction
"""

import json
from GameNetAPI import ChannelMetrics

def test_channel_metrics():
    """Test ChannelMetrics class"""
    print("Testing ChannelMetrics class...")
    
    # Create metrics instance
    metrics = ChannelMetrics()
    
    # Test initial state
    assert metrics.packets_received == 0
    assert metrics.packets_delivered == 0
    assert metrics.highest_seq == -1
    assert len(metrics.received_seqs) == 0
    
    # Test adding RTT
    metrics.add_rtt(10.5)
    metrics.add_rtt(12.3)
    metrics.add_rtt(11.1)
    
    assert len(metrics.rtts) == 3
    assert len(metrics.jitter_samples) == 2  # n-1 jitter samples
    assert abs(metrics.avg_rtt - 11.3) < 0.1
    
    # Test sequence tracking
    metrics.packets_received = 8
    metrics.received_seqs = {0, 1, 2, 4, 5, 7, 8, 9}
    metrics.highest_seq = 9
    
    # Test PDR calculation
    pdr = metrics.calculate_pdr()
    expected_pdr = (8 / 10) * 100  # 8 out of 10 expected packets
    assert abs(pdr - expected_pdr) < 0.1, f"Expected PDR {expected_pdr}, got {pdr}"
    
    print("✅ All ChannelMetrics tests passed!")
    return True

def test_metrics_abstraction():
    """Test that metrics are abstracted in GameNetAPI"""
    print("\nTesting metrics abstraction in GameNetAPI...")
    
    from GameNetAPI import GameNetAPI
    
    # Create server-mode API
    api = GameNetAPI(isClient=False, host="localhost", port=4444, 
                     certfile="cert.pem", keyfile="key.pem")
    
    # Verify metrics dict exists
    assert hasattr(api, 'metrics'), "API should have metrics attribute"
    assert 'RELIABLE' in api.metrics, "API should have RELIABLE metrics"
    assert 'UNRELIABLE' in api.metrics, "API should have UNRELIABLE metrics"
    
    # Verify metrics are ChannelMetrics instances
    assert isinstance(api.metrics['RELIABLE'], ChannelMetrics)
    assert isinstance(api.metrics['UNRELIABLE'], ChannelMetrics)
    
    # Verify track_packet_metrics exists
    assert hasattr(api, 'track_packet_metrics'), "API should have track_packet_metrics method"
    
    # Verify statistics methods exist
    assert hasattr(api, 'get_statistics_summary'), "API should have get_statistics_summary method"
    assert hasattr(api, 'print_statistics'), "API should have print_statistics method"
    
    print("✅ Metrics abstraction tests passed!")
    return True

def test_certificate_abstraction():
    """Test that certificate generation is abstracted in GameNetAPI"""
    print("\nTesting certificate abstraction in GameNetAPI...")
    
    from GameNetAPI import GameNetAPI
    
    # Verify _ensure_certificates method exists
    api = GameNetAPI(isClient=False, host="localhost", port=4445,
                     certfile="cert.pem", keyfile="key.pem")
    assert hasattr(api, '_ensure_certificates'), "API should have _ensure_certificates method"
    
    print("✅ Certificate abstraction tests passed!")
    return True

def main():
    """Run all tests"""
    print("=" * 70)
    print("TESTING METRICS AND CERTIFICATE ABSTRACTION")
    print("=" * 70)
    
    try:
        test_channel_metrics()
        test_metrics_abstraction()
        test_certificate_abstraction()
        
        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED!")
        print("=" * 70)
        return 0
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())
