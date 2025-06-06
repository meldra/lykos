from __future__ import annotations

import re
from typing import Optional

from src.cats import Category
from src.containers import UserSet, UserDict
from src.decorators import command
from src.dispatcher import MessageDispatcher
from src.events import Event, event_listener
from src.functions import get_target, get_players, get_all_players
from src.gamestate import GameState
from src.messages import messages
from src.random import random
from src.users import User

ACTED = UserSet()
SWAPS: UserDict[User, tuple[int, int]] = UserDict()

@command("choose", chan=False, pm=True, playing=True, silenced=True, phases=("night",), roles=("master of teleportation",))
def choose(wrapper: MessageDispatcher, message: str):
    pieces = re.split(" +", message)
    if len(pieces) < 2:
        return
    var = wrapper.game_state
    target1 = get_target(wrapper, pieces[0], allow_self=True)
    target2 = get_target(wrapper, pieces[1], allow_self=True)
    if not target1 or not target2:
        return

    if target1 is target2:
        wrapper.send(messages["choose_different_people"])
        return

    index1 = var.players.index(target1)
    index2 = var.players.index(target2)
    SWAPS[wrapper.source] = (index1, index2)
    ACTED.add(wrapper.source)
    wrapper.send(messages["master_of_teleportation_success"].format(target1, target2))

@event_listener("send_role")
def on_send_role(evt: Event, var: GameState):
    for player in get_all_players(var, ("master of teleportation",)):
        player.send(messages["master_of_teleportation_notify"])
        if var.next_phase == "night":
            player.send(messages["players_list"].format(get_players(var)))

@event_listener("chk_nightdone")
def on_chk_nightdone(evt: Event, var: GameState):
    evt.data["acted"].extend(ACTED)
    evt.data["nightroles"].extend(get_all_players(var, ("master of teleportation",)))

@event_listener("player_win")
def on_player_win(evt: Event, var: GameState, player: User, main_role: str, all_roles: set[str], winner: Category, team_win: bool, survived: bool):
    if main_role == "master of teleportation":
        evt.data["count_game"] = False

@event_listener("transition_day_begin")
def on_transition_day_begin(evt: Event, var: GameState):
    swaps = list(SWAPS.values())
    random.shuffle(swaps)
    for (index1, index2) in swaps:
        target1 = var.players[index1]
        target2 = var.players[index2]
        var.players[index2] = target1
        var.players[index1] = target2
    ACTED.clear()
    SWAPS.clear()

@event_listener("reset")
def on_reset(evt: Event, var: GameState):
    ACTED.clear()
    SWAPS.clear()

@event_listener("get_role_metadata")
def on_get_role_metadata(evt: Event, var: Optional[GameState], kind: str):
    if kind == "role_categories":
        evt.data["master of teleportation"] = {"Neutral", "Nocturnal"}
