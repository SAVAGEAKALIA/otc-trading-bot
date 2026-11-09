"""Module for IQ option profile resource."""

from trading_platform.vendor.iqoptionapi.iqoptionapi.http.resource import Resource


class Profile(Resource):
    """Class for IQ option profile resource."""
    # pylint: disable=too-few-public-methods

    url = "profile"
