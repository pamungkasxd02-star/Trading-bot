import json
from urllib.parse import parse_qs

from spotlab.notifier import TelegramNotifier
from spotlab.telegram_menu import MAIN_ROWS, keyboard, route


def test_command_interrupts_prompt_and_unknown_input_opens_menu():
    state = {}
    route("Lihat candle", state, 100)
    assert route("/status", state, 101)[0] == "/status"
    assert "menu_prompt" not in state
    assert route("halo", state, 102)[0] == "/menu"


def test_keyboard_serialized_in_transport(monkeypatch):
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"ok": true}'

    def send(request, timeout):
        requests.append(parse_qs(request.data.decode()))
        return Response()

    monkeypatch.setattr("spotlab.notifier.urlopen", send)
    notifier = TelegramNotifier("test-only", "12345", True)
    notifier.send("Menu", reply_markup=keyboard(MAIN_ROWS))
    assert json.loads(requests[0]["reply_markup"][0])["keyboard"] == MAIN_ROWS
    notifier.send("Normal")
    assert "reply_markup" not in requests[1]


def test_chart_wizard_validates_interval_and_back_navigation():
    state = {}
    route("Lihat candle", state, 100)
    command, prompt, markup = route("ETH/BTC", state, 101)
    assert command == "" and "ETH/BTC" in prompt
    assert "15m" in str(markup)
    command, prompt, _ = route("2m", state, 102)
    assert command == "" and "valid" in prompt
    assert state["menu_prompt"]["coin"] == "ETH/BTC"
    route("Kembali", state, 103)
    assert "coin" not in state["menu_prompt"]
    route("SOL", state, 104)
    assert route("1M", state, 105)[0] == "/chart SOL 1M"
    assert "menu_prompt" not in state


def test_analysis_presets_and_expiry():
    state = {}
    route("Analisis coin", state, 100)
    route("bitcoin", state, 101)
    assert route("Swing", state, 102)[0] == "/analyze bitcoin 4h 1d 1w"
    route("Lihat candle", state, 200)
    route("BTC", state, 201)
    assert "kedaluwarsa" in route("15m", state, 501)[1]
    assert "menu_prompt" not in state


def test_wizard_cancel_and_direct_commands_do_not_become_coin_names():
    state = {}
    route("Lihat candle", state, 100)
    route("BTC", state, 101)
    assert route("Batal", state, 102)[0] == "/menu"
    route("Analisis coin", state, 103)
    assert route("/auto off", state, 104)[0] == "/auto off"
    assert "menu_prompt" not in state
