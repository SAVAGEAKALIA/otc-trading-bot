"""IQ Option adapters; optional ledger history loads only when requested."""
from .api import IQOptionAPI, build_legacy_api
from .execution import BinaryDirection, BinaryOrderCommand, BinaryOrderSubmission, IQOptionBinaryExecutionAdapter

__all__ = ['IQOptionAPI', 'build_legacy_api', 'BinaryDirection', 'BinaryOrderCommand', 'BinaryOrderSubmission',
           'IQOptionBinaryExecutionAdapter', 'IQOptionClosedOptionsHistory', 'IQOptionHistoryAPI',
           'IQOptionClosedOptionsPort', 'IQOptionSettlementGateway']

def __getattr__(name):
    from importlib import import_module
    modules = {'IQOptionClosedOptionsHistory':'history', 'IQOptionHistoryAPI':'history',
               'IQOptionClosedOptionsPort':'settlement', 'IQOptionSettlementGateway':'settlement'}
    if name not in modules:raise AttributeError(name)
    value=getattr(import_module('.'+modules[name],__name__),name)
    globals()[name]=value
    return value
