# Hivemind roadmap

What Hivemind can do today, what is being worked on, and what is planned.
Want to help with something? Open an issue saying which item, or send a pull
request (see [`CONTRIBUTING.md`](../CONTRIBUTING.md)). The item codes match the
project's own list, so use them when you ask.

**The goal:** every kind of Bee Swarm macro and every kind of AI helper in one
app. The classic gather-and-convert loop, boosting, quests, bosses, planters,
hive building and progress planning, all from one simple window.

Each item has one status:

| Status | Means |
|---|---|
| `built` | In Hivemind now. |
| `testing` | Built, being checked in the real game before it's switched on for everyone. Some of these run "look-only" first: they say what they would do, and do nothing. |
| `next` | Being built now or straight after. |
| `planned` | On the list, not started. |
| `researching` | We're working out whether and how it can be done. |

Ideas from the community are marked *(community idea)*; the names of the people
who sent them are in the app under Settings → Credits.

## At a glance

- **Now:** the [UI Preview](https://github.com/OfficialHivemind/Project-Hivemind/releases) for Windows,
  so people can try the app and tell us what they think.
- **Next:** test builds of the real bot (U15), a reliable hive claim after joining a server,
  goo collection (Q7), the red hive AI (H18) and AI models for weaker PCs (F0b).
- **Later:** a Mac version (RL7), auto update (U15f), auto-setup from your hive (F0),
  and many more community ideas below.

## How it plays

- **Plays on its own by looking at the screen** `built`: gathers, converts, walks home, recovers from deaths and rejoins. No game files are read or changed.
- **A14 · Steps aside for your other games** `built`: when you start another game, Hivemind pauses itself safely.
- **A1 · Route board** `built`: every walk's success rate, worst first, shown in the app.
- **A2 · Retires bad routes** `built`: a route that keeps failing is re-learnt or swapped for a reliable one.
- **A3 · Looks before risky climbs** `built`, and turns back cleanly when the way isn't clear.
- **A5 · Closes menus left open** `built` before walking out.
- **A18 · Closes Roblox pop-ups** `built` (shop and promo windows) by their own close button, never by guessing.
- **A25 · Answers boxes that block the screen** `built`: a stray Yes/No box is answered No (which never spends anything) instead of the bot getting stuck behind it.
- **A8 · Stuck detector** `built`: jumps, turns, then resets when it stops moving while gathering. The same for walking is planned.
- **A21 · Stays in the field** `built`: when pollen stops rising off the flowers, it heads home with the bag instead of wasting minutes.
- **A22 · Skips fields with an unreliable walk home** `built` until a Whirligig is held.
- **A22c · Homes by sight** `built` when no flowers are in view at all.
- **A22d · Keeps a Whirligig reserve** `built`: plants in Pine Tree while it holds fewer than two.
- **A9 · Learns from every death** `built`: each death gets a reason and an avoidance rule.
- **A28 · Ignores false deaths** `built`: a conversion that looks like a death no longer sends it the wrong way home.
- **A26 / A29 · Steadier joins** `built`: scrolls the Roblox home to find Bee Swarm, and clicks again when the first click only focused the window.
- **A22b · Walks scaled to your real speed** `testing`: measures how fast you move (Haste and so on) and stretches or shortens each walk to match.
- **A32 · Better Pine Tree walks home** `testing`.
- **Reliable hive claim on a fresh server join** `next`.
- **A4 · Commando Chick egg escape** `next`: step off the stair before the egg's damage lands.
- **A6 · Walk-home landing 98%+** `next`, measured every day.
- **A7 · Fewer rejoins** `next`: under one a day, so streaks like the Wealth Clock's are kept.
- **A24 · Field maps** `next`: a top-down map of each field, so it knows where it stands and steers back by the map.
- **A27 · Homing from odd spots** `next`: find the hive from anywhere, not only from the usual routes.
- **A10 · Disconnects** `planned`: kicked, server shutdown or a Roblox update ends in a clean rejoin.
- **A11 · Game health watchdog** `planned`: frozen or black screens noticed and fixed.
- **A12 · Unsticks keys and camera** `planned`: a stuck key, first-person camera or open chat box.
- **A13 · Frame tests** `planned`: every reader tested on saved real frames, so a change can't quietly break one.
- **A15 · Window robustness** `planned`: losing focus, a resolution change, a notification over the game.
- **A16 · Server events from chat** `planned`: "Vicious Bee has appeared", meteor showers, Honeystorms.
- **A17 · In-game clock** `planned`: day or night and the minute of the hour, for timers and night jobs.

## Proof: measuring what works

- **P1 · Benchmark scorecard** `built`: honey per hour, landing rate, rejoins, deaths and quests for each version, with a verdict that isn't fooled by honey arriving in lumps.
- **P3 · Every update checked before it installs** `built`: if a test fails, nothing is installed.
- **P4 · Today's honey per hour** `built` on the stats card, against yesterday and the last 7 days.
- **P10 · Where the time goes** `built`: gathering, walking, converting, errands, bosses, stuck, rejoins, as a daily pie.
- **P16 · Errands priced in honey** `built`: the next few errands are ordered by profit per minute, and losers are skipped with a plain reason.
- **P2 · Auto-rollback** `testing`: if a new version makes less honey, put the previous one back and send an alert. Running look-only.
- **P19 · Honey read on every trip** `next`, so every trip counts in the numbers.
- **P20 · Nightly benchmark** `next`.
- **P5 · Self-learning experiments** `planned`: patterns, sprinklers, fields and timings tried in fair turns; the winner is kept automatically.
- **P6 · Weekly report** `planned`: what was tried, what won, the honey change.
- **P7 · Daily self-review** `planned`: the day's three biggest losses, each with a proposed fix.
- **P9 · Wax cycles with planters** `planned` *(community idea)*: an end-game planter rotation for the fields that drop wax, with the wax counted.
- **P11 · Cost and value of every feature** `planned`: drop what costs more honey than it brings.
- **P12 · Replay simulator** `planned`: a new version plays recorded trips "on paper" first, then side by side with the live one.
- **P13 · Heatmap** `planned`: honey per hour by field and time of day.
- **P14 · Benchmark in the app** `planned`: each version's verdict on the Stats tab.
- **P17 · Fewer inventory reads** `planned`: a little more gathering time.

## Knowing the game

- **K7 · Mob table** `built`: every mob's field, respawn time, drops and danger.
- **K8 · Beequip knowledge** `built`: every beequip, its waxes, and the best ones for blue, red and white hives.
- **K1 · Game-mechanics model** `planned`: capacity, convert rate, colour bonuses, so it can predict honey per hour before trying.
- **K2 · Bee knowledge** `planned`: every bee's abilities and tokens, and what your hive makes.
- **K3 · Items and boosts** `planned`: Glitter, dice, Enzymes, Oil, extracts, Field Boosters.
- **K4 · Nectars** `planned`: the five nectars, their buffs and how fast they fade.
- **K5 · Quest rewards** `planned` for every bear's chain.
- **K6 · Ticket and honey value** `planned` of dispensers, shops, eggs and Memory Match.
- **K9 · Amulets** `planned`: which rolls are better.
- **K10 · Stickers** `planned`: Sticker Stack value and the Sticker Printer.
- **K11 · Mutations** `planned`: which are worth chasing for your hive colour.
- **K12 · Kept up to date** `planned`: check the wiki after game updates and flag what changed.

## Progress planning

- **G1 · Blue, red and white progression** `built`, with a selector in the app.
- **G2 · Knows your stage** `built` from what it reads in game; anything it can't read yet becomes a question.
- **G3 · Your goals first** `built`, then the progression plan, all labelled.
- **G4 · Goals tab** `built`, plus "saving for..." in the simple view.
- **G9 · Session goals with an "is it possible?" check** `built` *(community idea)*: set what you want done in a time ("8 hours: honey, a quest, a piece of gear") and it says yes, likely or no, with an estimate, then plans for it.
- **G11 · Materials checklist** `built` *(community idea)*: what your next gear still needs. Planned next: read the inventory, say the fastest way to the next gear or planter, and gather where the missing materials drop.
- **G13 · Asks fewer questions** `built`: it checks shops itself to see what you own instead of asking.
- **G13b · Spots your gear by itself** `testing`.
- **G10 · Your own progression plan** `built` *(community idea)*: reorder, add or remove goals, and share it as a preset (the route editor).
- **G12 · Auto budget, and building alts** `testing` *(community idea)*: the PLAN tab's Fuzzy alt, Tad alt and Hybrid choices (the fastest way to all of them); the budget part is still planned.
- **G5 · Long-term strategist** `planned`: a weeks-ahead plan of what to buy, craft and quest, and why.
- **G6 · Setup wizard** `planned`: builds the missing readers (gear, amulets, badges, bee levels) on first run.
- **G7 · Re-plans after big events** `planned`: a new gifted bee, a mythic, new gear.
- **G8 · "What should I buy next?"** `planned`, answered on your phone.

## The brain

- **B5 · Cooldown scheduler** `built`: dispensers, bosses, planters and Memory Match fitted between gathers with no idle time.
- **B16 · Every timer booked** `built`: dispensers, boosters and the Wealth Clock, from the game's own prompts.
- **B19 · Boost keeper** `built` *(community idea)*: keeps chosen boosts alive, including through converts.
- **B20 · One planner, every errand priced** `testing`: quests, errands and gathering compared in honey, one plan.
- **U19b · Field boosters only where it will gather** `next`.
- **B1 · Buff brain** `planned`: Melody, Focus, Precision, Baby Love, Haste, Bear Morph timed into gathering.
- **B2 · Boost stacking** `planned`: Glitter, dice, Enzymes and Oil inside a field boost.
- **B3 · Smarter converting** `planned`: Honey Bee blessing, converter timing, Balloon Blessing.
- **B4 · Field choice from everything** `planned`: measured rates, quests and boosts together.
- **B6 · Night plan** `planned`: Vicious Bee, night Memory Match, Werewolf, Wild Windy Bee.
- **B7 · Risk model** `planned`: skip a field while a dangerous mob is up.
- **B8 · Every decision explained** `planned` in plain English.
- **B9 · No more questions** `built`: it decides on its own, tells you what it decided, and one tap undoes it.
- **B10 · Travel optimiser** `planned`: cannons, glider and parachute, shortest routes, errands batched by area.
- **B11 · Field Boosters on timer** `planned`, gathering in the boosted field while it lasts.
- **B12 · Marks** `planned`: stand on Honey, Pollen and Precise Marks.
- **B13 · Converters** `planned`: Instant and Micro-Converters used where they save the most time.
- **B14 · Session modes** `planned`: "farm until X honey", "max tickets", "quests only", "boss night".
- **B15 · Schedules** `planned`: quiet hours and automatic pauses at times you choose.

## Gathering and tokens

- **T17 · Make and share gather patterns** `built` *(community idea)*, in the app's pattern studio.
- **Token chasing with a "token brain"** `built`: weighs each token's value against the walk to it.
- **T2 · Token AI v2** `testing` *(community idea)*: more token kinds and buff rules (Token Link, balloons, Haste, Flame), the most wanted first.
- **Per-field experiments** `testing`: when to convert and whether to chase tokens, tried field by field.
- **F2 · Token detector retrained** `next` on what it learnt from its own chases.
- **T1 · Token training data** `planned`, with unsure frames kept for quick labelling.
- **T3 · Patterns per field** `planned`: pattern, size and sprinkler spot tried and compared.
- **T4 · Sprinkler detection** `planned`.
- **T5 · Puffshrooms** `planned` *(community idea)*: find and pop them when they spawn (an option). Also a fix for Sprout pickup.
- **T6 · Duped tokens** `planned`: recognise them and grab them.
- **T7 · Blue hive extras** `planned`: Bubble Bloat, Buoyant and Tadpole bubbles, Balloon value.
- **T8 · Red hive extras** `planned`: Flames, Scorch, Rage tokens, and standing in flames as an option.
- **T9 · White hive extras** `planned`: Precision, Inspire, Gummy goo, Tabby Love, and standing in Precise targets.
- **T10 · Stays centred in the field** `planned`.
- **T11 · Faster vision** `planned`, so chases start sooner.
- **T12 · Converts at the best moment** `planned`, not only when the bag is full.
- **T13 · Flower bloom map** `planned`: track which patches have regrown.
- **T14 · Bloom hunting** `planned` *(community idea)*: pop Blooms and catch the petals.
- **T14b · Petal choice and best drops** `planned` *(community idea)*: pick which petals to collect and how many; a list of the best materials found (switchable off).

## Quests

- **Quests** `built`: reads the quest menu, works on the steps it can do, hands quests in.
- **Q3 · Night Vicious Bee kills** `built` for quests that ask for them.
- **Q4 · Spirit Bear, Dapper Bear and Riley Bee chains** `built`.
- **Q8 · The right colour for petal quests** `built` *(community idea)*: farms the colour Bucko or Riley asked for.
- **Q9 · Quest fields unblocked** `testing`: quests send it to the fields they need.
- **Q1 · Hand-ins for every bear** `next`: Bucko, Polar, Honey Bee, Black, Brown, Mother, Panda, Science.
- **Q2 · Army Ants** `next` via the Ant Challenge.
- **Q3b · Finds the Vicious Bee's stinger** `next` and walks to it.
- **Q5 · Quest-aware fields** `next`.
- **Q7 · Goo collection** `next` *(community idea)*: use the Gummy Bee's ability for goo quests.
- **Q6 · "Collect X" steps** `planned`: red boost tokens, petals and Blooms that quests ask for.
- **Onett, Gummy Bear and Stick Bug chains** `planned`, once your account is ready for them.
- **The best chain by reward** `planned`.

## Bosses and mobs

- **Bug runs and the Coconut Crab fight** `built`, on their respawn timers.
- **M4 · Coconut Crab** `built` *(community idea)*. King Beetle, Tunnel Bear and Stump Snail are planned, each when your hive is ready.
- **M8b · Fireflies at night** `built`: collects the Moon Charms they leave.
- **M2b · Mondo Chick loot** `testing`: walks the field after a kill and picks up the drops.
- **M10 · Server hopping** `testing` *(community idea)*: optional and off by default, for Vicious Bee, Windy Bee and sprouts, or to leave a laggy server.
- **M11 · Join a chosen server** `testing`: join a friend's server by name.
- **M1 · Mob loop** `next`: Werewolf, Spider, Rhino, Ladybug, Mantis and Scorpion, when the drops or quests are worth it.
- **M5 · Vicious Bee hopping** `next` *(community idea)*: hop to night servers for stingers.
- **M2 · Mondo Chick** `planned` at the top of the hour when worth it.
- **M3 · Commando Chick** `planned` *(community idea)*, safely.
- **M3b · Keep your distance from mobs** `planned` *(community idea)*: step back and let the bees fight.
- **M10b · Shared night servers** `planned` *(community idea)*: Hivemind players share night servers for Vicious Bee.
- **M6 · Wild Windy Bee** `planned` for white hives.
- **M7 · Boss loot checked by sight** `planned`.
- **M8 · Stump Snail amulet progress** `planned`.
- **M9 · Mob kill counters** `planned` for badges and quests.

## Your hive

- **H12 · Auto-Jelly switch** `built`.
- **H13 · Hive planner** `built`: your hive drawn as the real hex grid; plan which bee goes where.
- **H13b · Reads every slot** `built`.
- **H17 · Hive presets** `built` *(community idea)* for blue, red and white.
- **H13d · Hatch by plan** `testing`: new bees go into the slot your plan wants filled.
- **H16 · Gifted Basic grinding** `testing`: Basic Egg, then jelly, until the Basic bee is gifted.
- **H4 · Beequips** `next`: equip, wax and swap by hive colour.
- **H18 · Red hive AI** `next`: Scorching Star tokens, flames, Precise targets. Needs red-hive testers.
- **H1 · Royal Jelly rolling** `planned` *(community idea)*: stops on gifted or mythic, or on the bee you pick; Star Jelly only if you turn it on; Diamond Eggs are kept.
- **H2 · Treats and bond** `planned` for the bees that matter.
- **H3 · Hive analysis** `planned` *(community idea)*: which bees to add or drop.
- **H4b · Wax calculator** `planned` *(community idea)*: the odds of each beequip stat.
- **H5 · Mutations** `planned`.
- **H6 · Gear buying** `planned`: tools, bags, masks, guards, boots.
- **H7 · Amulet grinding** `planned`: keep the better roll.
- **H8 · Star Egg and Gifted Star timing** `planned`.
- **H9 · Sprinkler upgrades** `planned` when they pay back.
- **H10 · Hive slots** `planned`, timed after gear.
- **H11 · Bee levels** `planned`: treats to reach the next ability.
- **H15b · Alt time-share** `planned`: an alt plays while the main is closed.
- **H14 · Fuzzy alts** `researching`: help build Fuzzy Bee alts for your private server.
- **H15 · Two accounts at once** `researching`.

## Planters and nectar

- **N4 · Nectar vials** `built` *(community idea)*: the Nectar Condenser and vial collection.
- **N6 · Pro Shop planters** `built`.
- **N5 · Dapper Bear's shop** `next` (the Plastic Planter).
- **N1 · Nectar kept high** `planned` with a planter rotation.
- **N2 · Choose your nectars** `planned` *(community idea)*: which nectars, their priority and how much; planters harvested when grown.
- **N3 · Next planter** `planned`, bought when it pays back.

## Shops, crafting and items

- **Planters, dispensers, buying and crafting** `built` within your settings. **It never spends Robux.**
- **$11 · Hotbar rules** `built`: use chosen items every N minutes, at each convert, while gathering, or in a chosen field.
- **S15 · Sticker Stack ticket boost** `next`.
- **$1 · Every dispenser** `planned` checked: Treat, Blueberry, Strawberry, Coconut, Glue, Royal Jelly, Honey, Ant and Robo passes.
- **$2 · Wealth Clock streak** `planned` protection.
- **$3 · Blender** `planned`: craft by value.
- **$4 · Wind Shrine** `planned` *(community idea)*: donations by value.
- **$5 · Tickets** `planned`: spent where they're worth most.
- **$6 · Honey reserve** `planned`: never spend what the next goal needs.
- **$7 · Codes** `planned`: redeem new codes you send it.
- **$8 · Daily shopping list** `planned`, within the reserve.
- **$9 · Ant and Robo passes** `planned`, timed for the best reward.
- **$10 · Forecasts** `planned`: "you'll afford X in about N hours".

## Mini-games, macro modes and events

- **X1 · Memory Match** `built`, with a fixed second pick.
- **X5 · Stick Bug challenge** `next` *(community idea)*: find its field, dodge the Stick Nymphs, fight it alone.
- **X2 · Robo Pass** `planned`.
- **X3 · Sticker Printer** `planned`.
- **X4 · Honeystorm summons** `planned`.
- **X6 · Ant Challenge** `planned` for score.
- **CM1 · Robo Bear Challenge runs** `planned` *(community idea)*: drive runs with your choice of upgrades, with an on/off switch.
- **CM2 · Badge farming** `planned` *(community idea)*.
- **CM3 · Combo and guide rotations** `researching` *(community idea)*.
- **I1 · Beesmas** `planned` *(community idea)*: Stockings, Samovar, Honey Wreath, Gingerbread Bear and more.
- **I2 · Egg hunts and seasonal quests** `planned`.
- **I3 · Event detector** `planned`: notices an event and adds its jobs.

## The app

- **The desktop app** `built`: live view, settings, stats, a pattern studio, a hive planner, credits.
- **U1 · Simple and Advanced modes** `built`, presets and Stream mode.
- **U2 · Goals tab and route board** `built`.
- **U15d · UI Preview fixes from testing** `built` *(community idea)*.
- **U17b · Compare by config** `built`: see which of your setups does best.
- **U19 · Boosting tab** `built`: keep boosts alive, plus an AI that boosts.
- **U21 · Discord webhook alerts** `built` *(community idea)*.
- **Simpler Goals tab** `built`: pick and order goals, with the game's own images.
- **U18 · The new look** `testing`: five simple tabs (Macro, AI Progress, Boosting, Stats, Settings) with an Advanced mode for the rest.
- **U16 · Two modes, one app** `testing`: a classic macro you set up yourself, or the AI that progresses for you.
- **U17 · Graphs** `testing`: honey per hour over time, pollen by field, and more.
- **U12 · Every feature on one page** `testing`, each with an on/off switch.
- **U15b · Optional features off by default** `testing`, so you choose what runs.
- **U13 · Start when the PC starts** `testing` (an option).
- **U15 · Test builds of the real bot** `next` *(community idea)*: beginner friendly, Windows and Linux.
- **U15c · One file, one link** `next` to install.
- **U15e · Testers of every hive colour** `next`.
- **F0b · AI models for every PC** `next` *(community idea)*: Light, Standard and Heavy.
- **S12 · Runs well on weaker PCs** `next`.
- **U15f · Auto update** `planned` *(community idea)*: an option you turn on.
- **U23 · From your phone** `planned` *(community idea)*: check on and control Hivemind running on your PC.
- **F0 · Auto-setup** `planned` *(community idea)*: reads your hive and sets the pattern, token and quest priorities for you, and learns from there.
- **F0c · Bring your own AI key** `planned` *(community idea)*: an optional cloud vision model.
- **U14 · Tester program** `planned` across many kinds of PC.
- **U3 · "Why" timeline** `planned`: replay each trip with its decisions.
- **U4 · Live honey graph and mini-map** `planned`.
- **U5 · Decision inbox panel** `planned`.
- **U6 · Smoother animations** `planned`.
- **U7 · Accessibility** `planned`: keyboard navigation, font size, colour-blind-safe colours.
- **U8 · Help text on every setting** `planned`.
- **U9 · Time pie and feature values** `planned` on the Stats tab.
- **U10 · First-week tour** `planned`.
- **U11 · In-app notifications** `planned` for milestones.

## Alerts on your phone

- **TG1 · Telegram alerts and commands** `built`: status, screenshot, pause, resume, stop, report.
- **TG2 · Stats card with a graph** `built` four times a day.
- **TG10 · Clearer stats card** `built`.
- **TG11 · Big-spend alerts** `built`: anything large gets its own line, with the amount and why.
- **TG12 · Changelog to Discord** `built`.
- **F12 panic key** `built`.
- **TG3 · Goals from your phone** `planned`: set goals and ask what to buy next.
- **TG4 · Rare-drop alerts** `planned`: mythic, gifted, Star Treat, Diamond Egg, amulet.
- **TG5 · Weekly report and daily review** `planned`.
- **TG6 · Clips** `planned`: the last 30 seconds of play.
- **TG7 · Milestones** `planned`, with a screenshot.
- **TG8 · Modes and schedules from your phone** `planned`.
- **TG9 · "Why?"** `planned`: the last decision and its reason.

## Running well on your PC

- **S1 · Disk use kept small** `built`.
- **S2 · Memory use capped** `built`.
- **S3 · Read health** `built`: notices when its eyes stop reading the game well.
- **S11 · Old settings carried over** `built` after updates.
- **S14 · Resumes after a crash or rejoin** `built`: goals, quests, purchases and planters pick up where they left off.
- **S4 · Lighter on CPU and GPU** `built` *(community idea)*: the bot's screen reads use about a third less CPU, and a Low CPU mode (off by default) halves it again.
- **S5 · Backups** `planned` of what it has learnt.
- **S6 · Readable logs** `planned`, with one "what happened today" file.
- **S7 · "What's new" after each update** `planned`, in the app.
- **S8 · Code health** `planned`: smaller files, tests under a time limit.
- **S9 · Self-check at start** `planned`: every reader checked before farming.
- **O3 · Reproducible installs** `planned`: pinned dependencies.

## Platforms and releases

- **RL6k · Open source** `built`: this repository, under GPL-3.0.
- **RL6i · A real Windows installer** `built`: one setup file, no admin password.
- **UI Preview** `built`: a download for Windows to try the app with demo numbers (Linux coming).
- **RL6 · Windows version** `testing`.
- **RL1 · Linux package** `testing`: an AppImage.
- **RL1b · Universal Linux** `testing`: any desktop, set up in a few clicks.
- **RL3 · Other screen sizes** `planned`, UI scales and keybinds.
- **RL5 · Crash reports kept on your PC** `planned`. No telemetry.
- **RL7 · macOS** `planned` *(community idea)*.
- **RL6j · Use your PC while it plays** `researching` *(community idea)*, including Android emulators.
- **RL7b · Several accounts on macOS** `researching` *(community idea)*.
