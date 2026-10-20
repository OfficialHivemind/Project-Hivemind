# Prompt templates

Crops of the game's own top-centre prompt panel, for `act/hive.template_reader`.
Matching these costs about a millisecond; asking the vision model the same
question costs seconds and loads six gigabytes of weights, which matters on a
machine the owner is also using.

Each file here was cut from a REAL frame by `vision.banner.find`, and the label
is what the vision model transcribed from that same frame — not what someone
assumed it said.

| file | read as | source frame |
|---|---|---|
| `prompt_make_honey.png` | `Make Honey` | `var/incidents/223009-death/147_t+07.7s.jpg`, captured at the hive just after a respawn |
| `prompt_make_honey_empty.png` | `To Make Honey, Collect Pollen From Flower Fields` (the pad's banner with an EMPTY bag) | `var/respawn/203914-spawn.jpg`, on the owner's pad after a respawn with 0 pollen; the blue banner's connected component at (784, 62), 356x77 |
| `dialogue_leave.png` | `● Leave`, the exit row of an NPC options menu | `var/respawn/060550-unknown.jpg` (attempt 487), the Gifted Bucko Bee's menu ("Give Translator to Gifted Bucko Bee." / "Leave"), the 86x27 crop at (726, 818) inside the Leave row at (716, 813, 487x34); scored 1.000 on the four frames of that menu and at most 0.505 over 1,377 other saved frames (var/bears, var/places, var/respawn, attempts 483-487); read by `act/dialogue.leave_row` |
| `prompt_red_cannon.png` | `Fire the Red Cannon` (run-267, 00:33:00: "pressing E at the red cannon (panel: 'fire the red cannon')") | `var/routes/attempt-267/003300-natro_out_stump_via_red_cannon-03-cannon_approach-.jpg`, the text box `banner.find` returned, 283x58 at (853, 62); read by `vision/screenstate.red_cannon_prompt_score` and `red_cannon_prompt_box` (DESIGN 8dl) |

`template_reader` needs BOTH `Make Honey` and `Claim Hive` before it can replace
the model, and takes them as required arguments with no file lookup, so a
missing crop cannot silently become a default. `Claim Hive` is not here yet: no
frame captured so far contains it, because the panel only says that while
standing on a pad that is not yours.

**`banner.find` is not specific enough to label blindly.** Of 60 frames where it
found a "panel", at least one was the Pollen HUD pill. Anything cut from it has
to be looked at before it is saved.
