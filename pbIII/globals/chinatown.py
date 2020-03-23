import functools
import itertools
import operator

from mu.mel import ji
from mu.sco import old


class Fake(object):
    def __init__(self, m: tuple, n: tuple, mother: tuple) -> None:
        self.__n = n
        self.__m = m
        self.__mother = mother

    def convert2pitch(self, gender: bool = True) -> ji.JIPitch:
        primes = (self.__m, self.__n) if self.__n else (self.__m, [1])
        p = ji.r(*tuple(functools.reduce(operator.mul, p) for p in primes))
        if not gender:
            p = p.inverse()
        return p

    @property
    def is_fake(self) -> bool:
        return bool(self.__n)

    def clone(self, add_fake=True) -> tuple:
        lenm = len(self.__m)

        if self.is_fake:
            assert lenm >= 3
        else:
            assert lenm >= 2

        combinations = sorted(
            itertools.combinations(self.__m, lenm - 1),
            reverse=True,
            key=lambda x: sum(x),
        )

        data = tuple(Fake(item, self.__n, self.__m) for item in combinations)

        if not self.is_fake and add_fake:
            additional = Fake(
                self.__m, [p for p in self.__mother if p not in self.__m], self.__m
            )
            data += (additional,)

        return data


class Chinatown(object):
    def __init__(self, primes: tuple, fake_fakes: bool = False) -> None:
        lenp = len(primes)
        voices = [Fake(primes, None, primes).clone(add_fake=False)]
        voices += [[] for i in range(lenp - 2)]
        for nvox in range(len(voices) - 1):
            for fk in voices[nvox]:
                condition2clone = (not fk.is_fake, fk.is_fake and fake_fakes)
                if any(condition2clone):
                    voices[nvox + 1].extend(fk.clone())
        self.voices = voices

    def convert2voices(self, gender=True) -> tuple:
        len_voices = tuple(len(v) for v in self.voices)
        maxima = max(len_voices)
        rhythm_per_vox = [maxima // lv for lv in len_voices]
        return tuple(
            old.Melody(
                [
                    old.Tone(f.convert2pitch(gender=gender).normalize(), rhythm)
                    for f in vox
                ]
            )
            for vox, rhythm in zip(self.voices, rhythm_per_vox)
        )

    def convert2cadence(self, gender=True):
        return old.Polyphon(self.convert2voices()).chordify()


def convert_cadence2melody(cadence):
    melody = old.JIMelody([])
    for chord in cadence:
        de = chord.delay
        first = True
        if chord.pitch:
            sub = []
            for pitch in chord.pitch:
                if first is True:
                    sub.append(old.Tone(pitch, de, de))
                    first = False
                else:
                    sub.append(old.Tone(pitch, 0, de))
            sub = list(reversed(sub))
            melody.extend(sub)
        else:
            melody.append(old.Rest(de))
    return melody


if __name__ == "__main__":
    import pyteq

    ct = Chinatown((3, 5, 7, 11))
    CONCERT_PITCH = 120
    """
    melody = convert_cadence2melody(ct.convert2cadence())
    melody = [
        pyteq.MidiTone(
            ji.JIPitch(t.pitch, multiply=CONCERT_PITCH),
            t.delay,
            t.duration * 2,
            volume=0.65,
        )
        for t in melody
    ]
    harp_range = tuple(n for n in range(20, 125))
    f = pyteq.Pianoteq(melody, available_midi_notes=harp_range)
    f.export2wav("test0", preset='"Erard Player"')
    """
    FACTOR = 0.3
    for idx, voice in enumerate(ct.convert2voices()):
        print(voice)
        if idx == 0:
            vol = 0.68
        elif idx == 1:
            vol = 0.6
        elif idx == 2:
            vol = 0.48

        melody = [
            pyteq.MidiTone(
                ji.JIPitch(t.pitch, multiply=CONCERT_PITCH),
                t.delay * FACTOR,
                t.duration * FACTOR,
                volume=vol,
            )
            for t in voice
        ]
        harp_range = tuple(n for n in range(20, 125))
        f = pyteq.Pianoteq(melody, available_midi_notes=harp_range)
        f.export2wav("test{0}".format(idx), preset='"Concert Harp Daily"')
