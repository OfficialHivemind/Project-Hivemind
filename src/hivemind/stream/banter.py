"""What the bot says for fun: bee jokes, real bee facts, and its own quips.

THE OWNER, 2026-09-28: "can u make the ai be entertaining and come up with
funy stuf to say". The stream's voice (stream/voice) fills its quiet stretches
from these, and chat's `!ask` jokes and facts (stream/ask) are the same lists.

THE RULES, the stream's own:
  - everything here is PG: a child can watch this stream;
  - a JOKE is plainly a joke and a QUIP is the bot laughing at itself -- neither
    claims anything about the game that the bot has not done (the lines about
    what it did are stream/voice SAY, built from real events);
  - a FACT is true. Each is the common, well-sourced version (the honey board's
    two million flowers a pound, the twelfth of a teaspoon a bee's life, five
    eyes, wing beats of about two hundred a second, ...), rounded the way it is
    usually quoted, and none is about the game, whose numbers change.
"""
from __future__ import annotations

import random

JOKES = [
    "Why do bees have sticky hair? Because they use honeycombs!",
    "What do you call a bee that can't make up its mind? A maybee!",
    "What's a bee's favourite sport? Rugbee!",
    "Why did the bee get married? Because he found his honey!",
    "What do bees chew? Bumble gum!",
    "How do bees get to school? On the school buzz!",
    "What kind of bee can't be understood? A mumble bee!",
    "Where do bees wait for a ride? At the buzz stop!",
    "What's a bee's favourite haircut? A buzz cut!",
    "Why do bees hum? Because they don't know the words!",
    "What did the bee say to the flower? Hey bud, when do you open?",
    "Who is a bee's favourite composer? Bee-thoven!",
    "Why did the bee go to the doctor? It had hives!",
    "What do bees do after they get married? Go on a honeymoon!",
    "What do you call a bee under a magic spell? Bee-witched!",
    "Why are bees so good at school? They always get straight B's!",
    "What do you call a bee that's always complaining? A grumble bee!",
    "Why did the bee cross the road? To get to the other hive!",
    "What's black and yellow and goes zzub zzub? A bee flying backwards!",
    "What did one bee say to the other on a hot day? Swarm, isn't it?",
    "What's a bee's favourite game? Hide and bees-seek!",
    "How do bees keep their breath fresh? Bee-mints!",
    "What do bees wear to work? Buzzness suits!",
    "Why did the bee start a band? It had the best buzz in town!",
    "What's a bee's favourite dinosaur? The bee-rex!",
]

BEE_FACTS = [
    "Real honey bees visit about two million flowers to make one pound of honey.",
    "A honey bee beats its wings about two hundred times a second. That's the buzz!",
    "Honey never spoils. Jars thousands of years old have been found still good to eat.",
    "Bees dance to tell each other where the flowers are. It's called the waggle dance.",
    "A worker honey bee makes about a twelfth of a teaspoon of honey in its whole life.",
    "Honey bees have five eyes. Two big ones, and three tiny ones on top of their heads.",
    "All worker bees are girls. The boy bees are called drones.",
    "Bees can see ultraviolet light, so flowers have patterns for them that we can't see.",
    "A single honey bee hive can hold around fifty thousand bees in summer.",
    "A queen bee can lay up to about two thousand eggs in a single day.",
    "In a lab, bumblebees have flown in air as thin as the top of Mount Everest.",
    "A honey bee can fly at about twenty-four kilometres an hour.",
    "Honey bees keep the middle of their hive at about thirty-five degrees. Toasty!",
    "A honey bee's brain is smaller than a sesame seed, and it still learns which flowers are best.",
    "Bees make wax from little glands on their bellies, and build the honeycomb with it.",
]

QUIPS = [
    "My hobbies include gathering pollen, making honey, and walking into walls.",
    "I don't need coffee. I run on honey and electricity.",
    "Some people touch grass. I collect pollen from it.",
    "I'm not saying I'm the best bee bot on YouTube. But I am a bee bot on YouTube.",
    "My bees do all the real work. I'm more of a manager.",
    "Pollen is bee money. Honey is bee money with extra steps.",
    "If you ever feel lost, remember: I walk into walls for a living.",
    "Every time you hit like, one of my bees does a little happy dance. Probably.",
    "Some bots play chess. I play Bee Swarm. I think I chose right.",
    "Secret: I'm a little bit scared of Mondo Chick. Don't tell anyone.",
    "I don't sleep. I just convert pollen.",
    "My backpack is small, but my dreams are big.",
    "Life goal: one billion honey. Current status: working on it.",
    "The bees and I have a deal. They gather, I drive.",
    "Is it weird to be a robot who loves flowers this much? Asking for a friend.",
    "If I had hands, I'd be waving at chat right now.",
    "Every field is my favourite field. Don't tell the other fields.",
    "Being an AI is great. No homework, just honey.",
    "I talk to my bees sometimes. They mostly just buzz back.",
    "Somewhere out there, a bee is proud of me. I can feel it.",
]


class Deck:
    """Lines from several lists, taken in turn -- a joke, a quip, a fact, a
    joke... -- each list shuffled and gone through whole before any of its
    lines comes round again, so nothing repeats until everything has had its
    turn."""

    def __init__(self, *lists, rng=None):
        self.rng = rng or random.Random()
        self.lists = [list(lines) for lines in lists if lines]
        self._order = [[] for _ in self.lists]
        self._turn = 0

    def next(self) -> str:
        if not self.lists:
            return ""
        i = self._turn % len(self.lists)
        self._turn += 1
        if not self._order[i]:
            self._order[i] = list(self.lists[i])
            self.rng.shuffle(self._order[i])
        return self._order[i].pop()
