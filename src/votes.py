from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
import math
import re

from src.containers import UserDict, UserList, UserSet
from src.decorators import command
from src.functions import get_players, get_target, get_reveal_role
from src.messages import messages
from src.status import (try_absent, get_absent, get_forced_votes, get_all_forced_votes, get_forced_abstains,
                        get_vote_weight, try_day_vote_immunity, add_dying, kill_players)
from src.events import Event, event_listener
from src import channels, pregame, reaper, locks, config
from src.users import User
from src.dispatcher import MessageDispatcher
from src.gamestate import GameState

VOTES: UserDict[User, UserList] = UserDict()
GAMEMODE_VOTES: UserDict[User, str] = UserDict()
ABSTAINS: UserSet = UserSet()
ABSTAINED = False
LAST_VOTES = None
VOTED: int = 0

@command("vote", playing=True, pm=True, phases=("day",))
def day_vote(wrapper: MessageDispatcher, message: str):
    """Use this to vote for a candidate to be killed."""
    if not message:
        show_votes.func(wrapper, message)
        return
    if wrapper.private:
        return
    msg = re.split(" +", message)[0].strip()

    var = wrapper.game_state

    can_vote_bot = var.current_mode.can_vote_bot(var)

    voted = get_target(wrapper, msg, allow_self=var.self_vote_allowed, allow_bot=can_vote_bot, not_self_message="no_vote_self")
    if not voted:
        return

    if try_absent(var, wrapper.source):
        return

    ABSTAINS.discard(wrapper.source)

    for votee in list(VOTES):  # remove previous vote
        if votee is voted and wrapper.source in VOTES[votee]:
            break
        if wrapper.source in VOTES[votee]:
            VOTES[votee].remove(wrapper.source)
            if not VOTES.get(votee) and votee is not voted:
                del VOTES[votee]
            break

    if voted not in VOTES:
        VOTES[voted] = UserList()
    if wrapper.source not in VOTES[voted]:
        VOTES[voted].append(wrapper.source)
        channels.Main.send(messages["player_vote"].format(wrapper.source, voted))

    global LAST_VOTES
    LAST_VOTES = None # reset

    chk_decision(var)

@command("abstain", playing=True, phases=("day",))
def abstain(wrapper: MessageDispatcher, message: str):
    """Allow you to abstain from voting for the day."""
    var = wrapper.game_state
    if not var.abstain_enabled:
        wrapper.pm(messages["command_disabled"])
        return
    elif var.limit_abstain and ABSTAINED:
        wrapper.pm(messages["exhausted_abstain"])
        return
    elif var.limit_abstain and var.day_count == 1:
        wrapper.pm(messages["no_abstain_day_one"])
        return
    elif try_absent(var, wrapper.source):
        return
    for voter in list(VOTES):
        if wrapper.source in VOTES[voter]:
            VOTES[voter].remove(wrapper.source)
            if not VOTES[voter]:
                del VOTES[voter]
    ABSTAINS.add(wrapper.source)
    channels.Main.send(messages["player_abstain"].format(wrapper.source))

    chk_decision(var)

@command("retract", phases=("day", "join"))
def retract(wrapper: MessageDispatcher, message: str):
    """Takes back your vote during the day."""
    var = wrapper.game_state
    if wrapper.source not in get_players(var) or wrapper.source in reaper.DISCONNECTED or var.current_phase != "day":
        return

    global LAST_VOTES

    if wrapper.source in ABSTAINS:
        ABSTAINS.remove(wrapper.source)
        wrapper.send(messages["retracted_vote"].format(wrapper.source))
        LAST_VOTES = None # reset
        return

    for votee in list(VOTES):
        if wrapper.source in VOTES[votee]:
            VOTES[votee].remove(wrapper.source)
            if not VOTES[votee]:
                del VOTES[votee]
            wrapper.send(messages["retracted_vote"].format(wrapper.source))
            LAST_VOTES = None # reset
            break
    else:
        wrapper.pm(messages["pending_vote"])

@command("votes", pm=True, phases=("join", "day", "night"))
def show_votes(wrapper: MessageDispatcher, message: str):
    """Show the current votes."""
    var = wrapper.game_state
    pl = get_players(var)
    if var.current_phase == "join":
        # get gamemode votes in a dict of {mode: number of votes}
        gm_votes = list(Counter(GAMEMODE_VOTES.values()).items())
        gm_votes.sort(key=lambda x: x[1], reverse=True) # sort from highest to lowest

        votelist = []
        majority = False
        from src.gamemodes import GAME_MODES
        for gamemode, num_votes in gm_votes:
            # We bold the game mode if:
            # - The number of players is within the bounds of the game mode
            # - This game mode has a majority of votes
            # - It can be randomly picked
            # - No other game mode has a majority
            if (GAME_MODES[gamemode][1] <= len(pl) <= GAME_MODES[gamemode][2] and
                    (not majority or num_votes >= len(pl) / 2) and
                    (config.Main.get(f"gameplay.modes.{gamemode}.weight", 0) > 0 or num_votes >= len(pl) / 2)):
                gamemode = messages["bold"].format(gamemode)
                if num_votes >= len(pl) / 2:
                    majority = True
            votelist.append("{0}: {1}".format(gamemode, num_votes))

        msg = ", ".join(votelist)
        if len(pl) >= config.Main.get("gameplay.player_limits.minimum"):
            msg += messages["majority_votes"].format("; " if votelist else "", math.ceil(len(pl) / 2))

        with locks.join_timer:
            if pregame.START_VOTES:
                msg += messages["start_votes"].format(len(pregame.START_VOTES), pregame.START_VOTES)

        wrapper.send(msg)
        return

    if var.current_phase == "night":
        wrapper.pm(messages["voting_daytime_only"])
        return

    global LAST_VOTES

    if (wrapper.public and LAST_VOTES and config.Main.get("ratelimits.votes") and
            LAST_VOTES + timedelta(seconds=config.Main.get("ratelimits.votes")) > datetime.now()):
        wrapper.pm(messages["command_ratelimited"])
        return

    if wrapper.public and wrapper.source in pl:
        LAST_VOTES = datetime.now()

    if not VOTES:
        msg = messages["no_votes"]
        if wrapper.source in pl:
            LAST_VOTES = None # reset

    else:
        votelist = []
        for votee, voters in VOTES.items():
            votelist.append("{0}: {1} ({2})".format(votee, len(voters), ", ".join(p.nick for p in voters)))
        msg = ", ".join(votelist)

    wrapper.reply(msg, prefix_nick=True)

    avail = len(pl) - len(get_absent(var))
    votesneeded = avail // 2 + 1
    abstaining = len(ABSTAINS)
    if abstaining == 1: # *i18n* hardcoded English
        plural = " has"
    else:
        plural = "s have"

    to_send = messages["vote_stats"].format(len(pl), votesneeded, avail)
    if var.abstain_enabled:
        to_send += messages["vote_stats_abstain"].format(abstaining, plural)

    wrapper.reply(to_send, prefix_nick=True)

@command("vote", pm=True, phases=("join",))
def vote(wrapper: MessageDispatcher, message: str):
    """Vote for a game mode if no game is running."""
    if wrapper.public and message:
        from src.wolfgame import game
        return game.caller(wrapper, message)
    return show_votes.caller(wrapper, message)

# Specify timeout=True to force a vote and end of day even if there is no majority
# admin_forced=True will make it not count towards village's abstain limit if nobody is voted
def chk_decision(var: GameState, *, timeout=False, admin_forced=False):
    from src.trans import chk_win
    with locks.reaper:
        players = set(get_players(var)) - get_absent(var)
        avail = len(players)
        needed = avail // 2 + 1

        to_vote = []
        plurality = []
        max_count = 0

        for votee, voters in VOTES.items():
            votes = (set(voters) | get_forced_votes(var, votee)) - get_forced_abstains(var)
            count = sum(get_vote_weight(var, x) for x in votes)
            if count > max_count:
                max_count = count
                plurality = [votee]
            elif count == max_count:
                plurality.append(votee)

        if max_count >= needed:
            assert len(plurality) == 1
            to_vote = plurality

        behaviour_evt = Event("day_vote_behaviour", {"num_votes": 1, "kill_ties": False, "force": timeout}, votes=VOTES, players=avail)
        behaviour_evt.dispatch(var)

        num_votes = behaviour_evt.data["num_votes"]
        kill_ties = behaviour_evt.data["kill_ties"]
        force = behaviour_evt.data["force"]

        abstaining = False
        if not to_vote:
            if len((ABSTAINS | get_forced_abstains(var)) - get_all_forced_votes(var)) >= avail / 2:
                abstaining = True
            elif force:
                if len(plurality) == 1:
                    to_vote = plurality
                elif plurality and kill_ties:
                    if set(plurality) == set(get_players(var)): # killing everyone off? have you considered not doing that
                        abstaining = True
                    else:
                        to_vote.extend(plurality)
                elif not timeout:
                    # fnight counts as a timeout, so we want sunset instead of village_abstain
                    abstaining = True

        if abstaining:
            for forced_abstainer in get_forced_abstains(var):
                if forced_abstainer not in ABSTAINS: # did not explicitly abstain
                    channels.Main.send(messages["player_meek_abstain"].format(forced_abstainer))

            abstain_evt = Event("abstain", {})
            abstain_evt.dispatch(var, (ABSTAINS | get_forced_abstains(var)) - get_all_forced_votes(var))

            if not admin_forced:
                # if this is an admin-forced abstain that isn't also a timeout (currently doesn't exist in the bot),
                # then don't count the abstention against the village
                global ABSTAINED
                ABSTAINED = True
            channels.Main.send(messages["village_abstain"])

            from src.trans import transition_night
            transition_night(var)
            return

        if to_vote:
            global VOTED
            VOTED += len(to_vote) # track how many people we've killed today

            if timeout:
                channels.Main.send(messages["sunset_vote"])

            for votee in to_vote:
                voters = list(VOTES[votee])
                for forced_voter in get_forced_votes(var, votee):
                    if forced_voter not in voters: # did not explicitly vote
                        channels.Main.send(messages["impatient_vote"].format(forced_voter, votee))
                        voters.append(forced_voter) # they need to be counted as voting for them still

                if not try_day_vote_immunity(var, votee):
                    vote_evt = Event("day_vote", {}, players=avail)
                    if vote_evt.dispatch(var, votee, voters):
                        to_send = "day_vote_no_reveal"
                        if var.role_reveal in ("on", "team"):
                            to_send = "day_vote_reveal"
                        lmsg = messages[to_send].format(votee, get_reveal_role(var, votee))
                        channels.Main.send(lmsg)
                        add_dying(var, votee, "villager", "day_vote")

            kill_players(var, end_game=False)

        elif timeout:
            channels.Main.send(messages["sunset"])

        if timeout or VOTED >= num_votes:
            if chk_win(var, count_absent=False):
                return

            from src.trans import transition_night
            transition_night(var)

@event_listener("del_player")
def on_del_player(evt: Event, var: GameState, player: User, allroles: set[str], death_triggers: bool):
    if var.current_phase == "day":
        if player in VOTES:
            del VOTES[player] # Delete other people's votes on the player
        for k in list(VOTES):
            if player in VOTES[k]:
                VOTES[k].remove(player)
                if not VOTES[k]:  # no more votes on that person
                    del VOTES[k]
                break # can only vote once

        if player in ABSTAINS:
            ABSTAINS.remove(player)
    elif var.current_phase == "join":
        del GAMEMODE_VOTES[:player:]

@event_listener("transition_day_begin")
def on_transition_day_begin(evt: Event, var: GameState):
    global LAST_VOTES, VOTED
    LAST_VOTES = None
    VOTED = 0
    ABSTAINS.clear()
    VOTES.clear()

@event_listener("reset")
def on_reset(evt: Event, var: GameState):
    global ABSTAINED, LAST_VOTES, VOTED
    ABSTAINED = False
    LAST_VOTES = None
    VOTED = 0
    ABSTAINS.clear()
    VOTES.clear()
    GAMEMODE_VOTES.clear()
