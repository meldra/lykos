from __future__ import annotations

import itertools
from typing import Optional

from src.decorators import command
from src.dispatcher import MessageDispatcher
from src.events import Event, event_listener
from src.functions import get_players, get_all_players
from src.gamestate import GameState
from src.messages import messages
from src.roles.helper.shamans import setup_variables, get_totem_target, give_totem, totem_message
from src.status import is_silent
from src import users
from src.random import random

TOTEMS, LASTGIVEN, SHAMANS, RETARGET, ORIG_TARGET_MAP = setup_variables("shaman", knows_totem=True)

@command("totem", chan=False, pm=True, playing=True, silenced=True, phases=("night",), roles=("shaman",))
def shaman_totem(wrapper: MessageDispatcher, message: str):
    """Give a totem to a player."""

    var = wrapper.game_state

    totem_types = list(TOTEMS[wrapper.source].keys())
    totem, target = get_totem_target(var, wrapper, message, LASTGIVEN, totem_types)
    if not target:
        return

    if not totem:
        totem_types = list(TOTEMS[wrapper.source].keys())
        if len(totem_types) == 1:
            totem = totem_types[0]
        else:
            wrapper.send(messages["shaman_ambiguous_give"])
            return

    orig_target = target
    target = RETARGET[wrapper.source].get(target, target)
    if target in itertools.chain.from_iterable(SHAMANS[wrapper.source].values()):
        wrapper.send(messages["shaman_no_stacking"].format(orig_target))
        return

    given = give_totem(var, wrapper, orig_target, totem, key="shaman_success_night_known", role="shaman")
    if given:
        victim, target = given
        if victim is not target:
            RETARGET[wrapper.source][target] = victim
            ORIG_TARGET_MAP[wrapper.source][totem][victim] = target
        SHAMANS[wrapper.source][totem].append(victim)
        if len(SHAMANS[wrapper.source][totem]) > TOTEMS[wrapper.source][totem]:
            SHAMANS[wrapper.source][totem].pop(0)

@event_listener("transition_day_begin", priority=4)
def on_transition_day_begin(evt: Event, var: GameState):
    # Select random totem recipients if shamans didn't act
    pl = get_players(var)
    for shaman in get_all_players(var, ("shaman",)):
        if is_silent(var, shaman):
            continue

        ps = pl[:]
        for given in itertools.chain.from_iterable(LASTGIVEN[shaman].values()):
            if given in ps:
                ps.remove(given)
        for given in itertools.chain.from_iterable(SHAMANS[shaman].values()):
            if given in ps:
                ps.remove(given)
        for totem, count in TOTEMS[shaman].items():
            mustgive = count - len(SHAMANS[shaman][totem])
            for i in range(mustgive):
                if ps:
                    target = random.choice(ps)
                    ps.remove(target)
                    dispatcher = MessageDispatcher(shaman, users.Bot)
                    given = give_totem(var, dispatcher, target, totem, key="shaman_success_random_known", role="shaman")
                    if given:
                        SHAMANS[shaman][totem].append(given[0])

@event_listener("send_role")
def on_transition_night_end(evt: Event, var: GameState):
    chances = var.current_mode.TOTEM_CHANCES
    max_totems = sum(x["shaman"] for x in chances.values())
    ps = get_players(var)
    shamans = get_all_players(var, ("shaman",))
    for s in list(LASTGIVEN):
        if s not in shamans:
            del LASTGIVEN[s]

    shamans = list(shamans)
    random.shuffle(shamans)
    for shaman in shamans:
        if var.next_phase != "night":
            shaman.send(messages["shaman_notify"].format("shaman"))
            continue
        pl = ps[:]
        random.shuffle(pl)
        for given in itertools.chain.from_iterable(LASTGIVEN[shaman].values()):
            if given in pl:
                pl.remove(given)

        event = Event("num_totems", {"num": var.current_mode.NUM_TOTEMS["shaman"]})
        event.dispatch(var, shaman, "shaman")
        num_totems = event.data["num"]

        totems = {}
        for i in range(num_totems):
            target = 0
            rand = random.random() * max_totems
            for t in chances:
                target += chances[t]["shaman"]
                if rand <= target:
                    if t in totems:
                        totems[t] += 1
                    else:
                        totems[t] = 1
                    break
        event = Event("totem_assignment", {"totems": totems})
        event.dispatch(var, shaman, "shaman")
        TOTEMS[shaman] = event.data["totems"]

        num_totems = sum(TOTEMS[shaman].values())
        if num_totems > 1:
            shaman.send(messages["shaman_notify_multiple_known"].format("shaman"))
        else:
            shaman.send(messages["shaman_notify"].format("shaman"))
        tmsg = totem_message(TOTEMS[shaman])
        for totem in TOTEMS[shaman]:
            tmsg += " " + messages[totem + "_totem"]
        shaman.send(tmsg)
        shaman.send(messages["players_list"].format(pl))

@event_listener("get_role_metadata")
def on_get_role_metadata(evt: Event, var: Optional[GameState], kind: str):
    if kind == "role_categories":
        evt.data["shaman"] = {"Village", "Safe", "Nocturnal"}
    elif kind == "lycanthropy_role":
        evt.data["shaman"] = {"role": "wolf shaman", "prefix": "shaman"}

@event_listener("default_totems")
def set_shaman_totems(evt: Event, chances: dict[str, dict[str, int]]):
    chances["death"]        ["shaman"] = 1
    chances["protection"]   ["shaman"] = 1
    chances["silence"]      ["shaman"] = 1
    chances["revealing"]    ["shaman"] = 1
    chances["desperation"]  ["shaman"] = 1
    chances["impatience"]   ["shaman"] = 1
    chances["pacifism"]     ["shaman"] = 1
    chances["influence"]    ["shaman"] = 1
