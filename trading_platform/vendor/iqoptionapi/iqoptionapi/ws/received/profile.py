"""Module for IQ option websocket."""
import trading_platform.vendor.iqoptionapi.iqoptionapi.global_value as global_value

def profile(api, message):
    if message["name"] == "profile":
        api.profile.msg = message["msg"]
        if api.profile.msg != False:
            # ---------------------------
            try:
                api.profile.balance = message["msg"]["balance"]
            except:
                pass
            # Select an initial balance. Practice (type 4) remains the
            # preferred bootstrap account, but some accounts do not expose a
            # practice balance. In that case use the server-selected balance
            # or any available account so stable_api.connect() can return and
            # the application can explicitly switch to its configured mode.
            if global_value.balance_id is None:
                balances = message["msg"].get("balances", [])
                practice = next(
                    (balance.get("id") for balance in balances if balance.get("type") == 4),
                    None,
                )
                server_selected = message["msg"].get("balance_id")
                fallback = next(
                    (balance.get("id") for balance in balances if balance.get("id") is not None),
                    None,
                )
                global_value.balance_id = practice or server_selected or fallback
            try:
                api.profile.balance_id = message["msg"]["balance_id"]
            except:
                pass

            try:
                api.profile.balance_type = message["msg"]["balance_type"]
            except:
                pass

            try:
                api.profile.balances = message["msg"]["balances"]
            except:
                pass
