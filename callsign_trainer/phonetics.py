"""Spelling words and voice-specific pronunciation adjustments."""

import string

PHONETIC_WORDS = dict(
    zip(
        string.ascii_uppercase + string.digits,
        (
            "Alpha Bravo Charlie Delta Echo Foxtrot Golf Hotel India Juliett "
            "Kilo Lima Mike November Oscar Papa Quebec Romeo Sierra Tango "
            "Uniform Victor Whiskey X-ray Yankee Zulu "
            "Zero One Two Three Four Five Six Seven Eight Nine"
        ).split(),
    )
)

# These spellings and Piper phoneme blocks were selected by listening.
PRONUNCIATION_OVERRIDES = {
    "nl": {
        "A": "alfa", "J": "djoelie-et", "M": "maik", "Q": "kwiebek",
        "R": "roomie-o", "T": "tenggo", "X": "eks reej",
        "1": "wan", "2": "toe", "3": "trie", "4": "for", "5": "faiv",
        "6": "sikss", "7": "sevven", "8": "eit", "9": "nain",
    },
    "fr": {"H": "[[h]]o-tel", "M": "[[maik]]"},
    "de": {
        "E": "ekko", "M": "maik", "X": "ex rej", "Z": "sulu",
        "1": "[[w]]an", "2": "tu", "3": "trie", "4": "for",
        "5": "[[faiv]]", "6": "[[s]]iks", "8": "[[e\u026at]]", "9": "nain",
    },
}

VOICE_PRONUNCIATION_OVERRIDES = {
    "en_US-lessac-medium": {"Z": "zoo loo"},
}


def phonetic_call_sign(call_sign, language=None, voice=None):
    overrides = PRONUNCIATION_OVERRIDES.get(language, {})
    voice_overrides = VOICE_PRONUNCIATION_OVERRIDES.get(voice, {})
    return " ".join(
        voice_overrides.get(character, overrides.get(character, PHONETIC_WORDS[character]))
        for character in call_sign
    )
