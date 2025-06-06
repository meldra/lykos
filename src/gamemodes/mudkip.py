from src.gamemodes import game_mode, GameMode, InvalidModeException
from src.messages import messages
from src.events import EventListener, Event
from src.gamestate import GameState
from src import channels, users

# someone let woffle commit while drunk again... tsk tsk
@game_mode("mudkip", minp=6, maxp=17)
class MudkipMode(GameMode):
    """Why are all the professors named after trees?"""
    def __init__(self, arg=""):
        super().__init__(arg)
        self.CUSTOM_SETTINGS.abstain_enabled = False
        self.CUSTOM_SETTINGS.start_with_day = True

        self.TOTEM_CHANCES = {
            "death"         : {"shaman": 1, "wolf shaman": 0, "crazed shaman": 0},
            "protection"    : {"shaman": 0, "wolf shaman": 1, "crazed shaman": 1},
            "silence"       : {"shaman": 0, "wolf shaman": 1, "crazed shaman": 0},
            "revealing"     : {"shaman": 0, "wolf shaman": 0, "crazed shaman": 0},
            "desperation"   : {"shaman": 0, "wolf shaman": 0, "crazed shaman": 0},
            "impatience"    : {"shaman": 0, "wolf shaman": 1, "crazed shaman": 0},
            "pacifism"      : {"shaman": 1, "wolf shaman": 0, "crazed shaman": 0},
            "influence"     : {"shaman": 1, "wolf shaman": 0, "crazed shaman": 1},
            "narcolepsy"    : {"shaman": 0, "wolf shaman": 0, "crazed shaman": 0},
            "exchange"      : {"shaman": 0, "wolf shaman": 0, "crazed shaman": 0},
            "lycanthropy"   : {"shaman": 0, "wolf shaman": 0, "crazed shaman": 1},
            "luck"          : {"shaman": 0, "wolf shaman": 0, "crazed shaman": 1},
            "pestilence"    : {"shaman": 1, "wolf shaman": 0, "crazed shaman": 1},
            "retribution"   : {"shaman": 0, "wolf shaman": 0, "crazed shaman": 1},
            "misdirection"  : {"shaman": 0, "wolf shaman": 1, "crazed shaman": 0},
            "deceit"        : {"shaman": 0, "wolf shaman": 0, "crazed shaman": 0},
        }

        self.set_default_totem_chances()

        # make assassin a primary role
        self.SECONDARY_ROLES.pop("assassin", None)

        self.ROLE_GUIDE = {
            6:  ["wolf", "cult leader", "investigator", "insomniac"],
            7:  ["jester"],
            8:  ["assassin"],
            9:  ["-jester", "doomsayer"],
            10: ["priest"],
            11: ["crazed shaman"],
            12: ["vengeful ghost"],
            13: ["wolf shaman"],
            14: ["amnesiac"],
            15: ["succubus"],
            16: ["shaman"],
            17: ["dullahan"]
        }

        self.EVENTS = {
            "day_vote_behaviour": EventListener(self.day_vote_behaviour),
            "daylight_warning": EventListener(self.daylight_warning)
        }

    def day_vote_behaviour(self, evt: Event, var: GameState):
        evt.data["kill_ties"] = True
        voters = sum(map(len, evt.params.votes.values()))
        if voters == evt.params.players:
            evt.data["force"] = True

    def daylight_warning(self, evt: Event, var: GameState):
        evt.data["message"] = "daylight_warning_killtie"
