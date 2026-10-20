"""Stream mode: the bot on a 24/7 live stream, and what its chat may do.

    chat.py     reading chat: Twitch anonymously, or a file another tool writes
    show.py     the games chat plays: votes, predictions, the leaderboard
    gate.py     THE ONE GATE a chat vote passes through before it changes a trip
    privacy.py  THE ONE GATE every word passes before the stream draws it, and
                the parts of the game picture it masks (DESIGN 8ec)
    extras.py   the commentary line, today's records and streaks, the quest
                bars, the midnight recap and the clip markers (DESIGN 8ec)

All but the gate run in the GUI. The gate runs in the bot, because the bot is
the only thing that can know, at the moment a field is chosen, whether chat's
pick is still one it would go to. DESIGN 8dv.
"""
