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
