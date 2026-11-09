from trading_platform.brokers.iqoption import IQOptionAPI


def test_iqoption_api_boundary_is_runtime_protocol():
    assert getattr(IQOptionAPI, "_is_protocol", False)
