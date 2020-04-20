import operator
import os

import natsort

from mu.utils import activity_levels
from mu.utils import infit
from mu.utils import interpolations
from mu.utils import tools

from mutools import synthesis


"""Module for Speech processing / SpeechEngine.

Unlike other engines, the SpeechEngine barely depends on data from other
voices (it is rather independent from surrounding sounds). Because of this
special feature, the Engines that will be used in the Segment object will
become initalised outside of the respective Segment object.

Different engines include:

    (1) BrokenRadio aka the time machine

        Class to process samples that has been cut in small slices. It's possible
        to mix multiple sources and to process each short sound file individually.
        Furthermore background noise can be added.

    (2) SimplePlayer & Looper

        Class to process one long sample.
"""


class SlicePlayer(synthesis.pyo.EventInstrument):
    fadein = 0.02
    fadeout = 0.03

    def __init__(self, **args) -> None:
        synthesis.pyo.EventInstrument.__init__(self, **args)

        attributes_to_set_zero = (
            "original_lv",
            "harmonizer_lv",
            "ringmodulation_lv",
            "filter_lv",
            "distortion_lv",
            "noise_lv",
            "lorenz_lv",
        )
        attributes_to_set_n = (
            ("lv", 1),
            ("rm_freq", 200),
            ("filter_freq", 200),
            ("filter_q", 1),
            ("h_transpo", -2),
            ("lorenz_pitch", 0.4),
            ("lorenz_chaos", 0.5),
            ("chenlee_pitch", 0.75),
            ("chenlee_chaos", 0.5),
        )
        attributes_to_set_n += tuple((attr, 0) for attr in attributes_to_set_zero)
        for attribute, value in attributes_to_set_n:
            try:
                getattr(self, attribute)
            except AttributeError:
                setattr(self, attribute, value)

        fade = synthesis.pyo.Fader(fadein=self.fadein, fadeout=self.fadeout).play(
            dur=float(self.dur)
        )
        fade *= float(self.lv)

        if self.path is not None:
            self.osc = SlicePlayer.make_osc(self.path, mul=fade).play(dur=self.dur)
            self.original = SlicePlayer.make_osc(
                self.path, mul=fade * self.original_lv
            ).out(1, dur=self.dur)
            self.h = synthesis.pyo.Harmonizer(
                self.osc, transpo=self.h_transpo, mul=self.harmonizer_lv
            ).out(1)
            self.filtered = synthesis.pyo.Reson(
                self.osc, freq=self.filter_freq, q=self.filter_q, mul=self.filter_lv
            ).out(1)
            self.distr = synthesis.pyo.Disto(self.osc, mul=self.distortion_lv).out(1)
            self.rm = (
                synthesis.pyo.Sine(self.rm_freq) * self.osc * self.ringmodulation_lv
            ).out(1)

        # ambient noise
        noise_dur = self.dur + self.fadein + self.fadeout
        self.noise_fader = synthesis.pyo.Linseg(
            [(0, self.ambient_noise_lv[0]), (self.dur, self.ambient_noise_lv[1])]
        ).play(dur=noise_dur)

        self.lorenz = synthesis.pyo.Lorenz(
            pitch=self.lorenz_pitch, chaos=self.lorenz_chaos, mul=self.lorenz_lv
        ).play(dur=noise_dur)

        self.brown = synthesis.pyo.BrownNoise(mul=self.noise_lv).play(dur=noise_dur)

        self.ambient_noise = ((self.brown + self.lorenz) * self.noise_fader * fade).out(
            1
        )

        # additional noise similar to sounds generated by natural radio, I love it!
        self.disturbance = synthesis.pyo.ChenLee(
            pitch=self.chenlee_pitch,
            chaos=self.chenlee_chaos,
            mul=fade * self.chenlee_lv,
        ).out(1)

    @staticmethod
    def make_osc(path: str, mul=1) -> synthesis.pyo.Osc:
        soundfile = synthesis.pyo.SndTable(path)
        return synthesis.pyo.Osc(soundfile, freq=soundfile.getRate(), interp=4, mul=mul)


class BrokenRadio(synthesis.PyoEngine):
    # aka the time machine
    # TODO(tidy up the whole class, make it less messy and redundant)

    # each effect has an activity_lv (0 -> never played, 10 -> always played)
    # and a (dynamic) level (has to be an object that understands 'next')
    __effects = (
        "original",
        "harmonizer",
        "filter",
        "distortion",
        "ringmodulation",
        "noise",
        "lorenz",
        "chenlee",
    )

    def __init__(
        self,
        sources: tuple,
        order_per_source: tuple = None,
        skip_n_samples_per_source: tuple = None,
        source_decider: tuple = None,
        activity_lv_per_effect: dict = {},
        level_per_effect: dict = {},
        volume: float = 1,
        curve: interpolations.InterpolationLine = interpolations.InterpolationLine(
            [
                interpolations.FloatInterpolationEvent(0.15, 0.5),
                interpolations.FloatInterpolationEvent(0.8, 1),
                interpolations.FloatInterpolationEvent(0.2, 1),
                interpolations.FloatInterpolationEvent(0, 0.2),
            ]
        ),
        duration: float = 10,
        interlocking: str = "parallel",
        pause_per_event: infit.InfIt = infit.Cycle((0,)),
        filter_freq_maker: infit.InfIt = infit.Cycle((200,)),
        filter_q_maker: infit.InfIt = infit.Cycle((0.5,)),
        rm_freq_maker: infit.InfIt = infit.Cycle((700,)),
        transpo_maker: infit.InfIt = infit.Cycle((-3, -1, -2, -5)),
        chenlee_chaos_maker: infit.InfIt = infit.Cycle((0.75, 1, 0.5, 0.8)),
        chenlee_pitch_maker: infit.InfIt = infit.Cycle((0.5, 0.75, 0.66)),
        lorenz_chaos_maker: infit.InfIt = infit.Cycle((0.5, 0.7, 0.6)),
        lorenz_pitch_maker: infit.InfIt = infit.Cycle((0.5, 0.6, 0.55)),
    ) -> None:

        super().__init__()

        if order_per_source is None:
            order_per_source = tuple("original" for i in sources)

        if source_decider is None:
            source_decider = infit.Cycle(range(len(sources)))

        if skip_n_samples_per_source is None:
            skip_n_samples_per_source = tuple(0 for i in sources)

        self.sources = sources
        self.interlocking = interlocking
        self.pause_per_event = pause_per_event
        self.order_per_source = order_per_source
        self.skip_n_samples_per_source = skip_n_samples_per_source
        self.volume = volume
        self.curve = curve
        self.__duration = duration
        self.source_decider = source_decider
        self.filter_q_maker = filter_q_maker
        self.filter_freq_maker = filter_freq_maker
        self.rm_freq_maker = rm_freq_maker
        self.transpo_maker = transpo_maker
        self.chenlee_chaos_maker = chenlee_chaos_maker
        self.chenlee_pitch_maker = chenlee_pitch_maker
        self.lorenz_chaos_maker = lorenz_chaos_maker
        self.lorenz_pitch_maker = lorenz_pitch_maker

        for effect in self.__effects:
            if effect not in activity_lv_per_effect:
                activity_lv_per_effect.update({effect: 0})

            if effect not in level_per_effect:
                level_per_effect.update({effect: infit.Cycle((1,))})

        self.level_per_effect = level_per_effect
        self.activity_lv_per_effect = activity_lv_per_effect

        self.path_per_source = BrokenRadio.detect_files(
            self.sources, order_per_source, skip_n_samples_per_source
        )
        self.data_per_source = BrokenRadio.detect_data_per_source(self.path_per_source)
        self.activity_object_per_effect = {
            effect: activity_levels.ActivityLevel() for effect in self.__effects
        }

        if interlocking == "parallel":
            self.maxima_n_events = min(len(paths) for paths in self.path_per_source)
        elif interlocking == "sequential":
            self.maxima_n_events = sum(len(paths) for paths in self.path_per_source)
        else:
            raise ValueError("Unknown interlocking: {}.".format(interlocking))

        if interlocking == "parallel":
            self.sample_key_per_event = tuple(
                (next(self.source_decider), idx) for idx in range(self.maxima_n_events)
            )

        elif interlocking == "sequential":
            self.sample_key_per_event = tools.euclidic_interlocking(
                *tuple(
                    tuple((idx, i) for i in range(len(source)))
                    for idx, source in enumerate(self.path_per_source)
                )
            )

        self.sample_path_per_event = tuple(
            self.path_per_source[source_idx][sample_idx]
            for source_idx, sample_idx in self.sample_key_per_event
        )
        ig1 = operator.itemgetter(1)
        self.duration_per_sample = tuple(
            ig1(self.data_per_source[source_idx][sample_idx])
            for source_idx, sample_idx in self.sample_key_per_event
        )

        self.duration_per_event = tuple(
            dps - 1 + next(pause_per_event) for dps in self.duration_per_sample
        )
        self.maxima_duration = sum(self.duration_per_event)

        try:
            assert self.maxima_duration > self.duration
        except AssertionError:
            msg = "Not enough samples for duration {}. Max duration {}".format(
                self.duration, self.maxima_duration
            )
            raise ValueError(msg)

    def copy(self) -> "BrokenRadio":
        return type(self)(
            self.sources,
            self.order_per_source,
            self.skip_n_samples_per_source,
            self.source_decider,
            self.activity_lv_per_effect,
            self.level_per_effect,
            self.volume,
            self.curve,
            self.duration,
            self.interlocking,
            self.pause_per_event,
            self.filter_freq_maker,
            self.filter_q_maker,
            self.rm_freq_maker,
            self.transpo_maker,
            self.chenlee_chaos_maker,
            self.chenlee_pitch_maker,
            self.lorenz_chaos_maker,
            self.lorenz_pitch_maker,
        )

    @property
    def duration(self) -> float:
        return self.__duration

    @staticmethod
    def detect_files(
        sources: tuple, order_per_source: tuple, skip_n_samples_per_source: tuple
    ) -> tuple:
        import random as random_shuffle

        random_shuffle.seed(10)

        files_per_source = []
        for path, order, skip_n_samples in zip(
            sources, order_per_source, skip_n_samples_per_source
        ):

            try:
                assert order in ("original", "reverse", "shuffle")
            except AssertionError:
                msg = "Unknown order: {}.".format(order)
                raise ValueError(msg)

            all_files = natsort.natsorted(os.listdir(path))[skip_n_samples:]

            if order == "reverse":
                all_files = tuple(reversed(all_files))
            elif order == "shuffle":
                all_files = list(all_files)
                random_shuffle.shuffle(all_files)
                all_files = tuple(all_files)

            soundfiles = filter(lambda f: f.endswith("wav"), all_files)
            files_per_source.append(tuple(path + f for f in soundfiles))

        return tuple(files_per_source)

    @staticmethod
    def detect_data_per_source(path_per_source: tuple) -> tuple:
        return tuple(
            tuple(synthesis.pyo.sndinfo(path) for path in source)
            for source in path_per_source
        )

    @staticmethod
    def convert_sample_names2pyo_objects(path: str, files: tuple) -> tuple:
        return tuple(synthesis.pyo.SndTable(path + f) for f in files)

    def render(self, name: str) -> None:
        self.server.recordOptions(
            dur=self.duration, filename="{}.wav".format(name), sampletype=4
        )

        import random as random_ambient_noise_lv

        random_ambient_noise_lv.seed(1)

        n_events = tools.find_closest_index(
            self.duration, tools.accumulate_from_zero(self.duration_per_event)
        )

        duration_per_event = self.duration_per_event[:n_events]
        sample_path_per_event = self.sample_path_per_event[:n_events]

        lv_per_effect = {
            "{}_lv".format(effect): tuple(
                next(self.level_per_effect[effect])
                if self.activity_object_per_effect[effect](
                    self.activity_lv_per_effect[effect]
                )
                else 0
                for i in duration_per_event
            )
            for effect in self.__effects
        }

        ambient_noise_lv_per_event = tuple(
            random_ambient_noise_lv.uniform(0.2, 0.4) for i in duration_per_event
        )
        ambient_noise_lv_per_event = tuple(
            (a, b)
            for a, b in zip(
                (0,) + ambient_noise_lv_per_event, ambient_noise_lv_per_event
            )
        )

        # general dynamic level for each slice
        event_lv = tuple(self.volume * lv for lv in self.curve(n_events, "points"))

        ################################################################

        # controlling different dsp parameter
        filter_freq_per_event = tuple(
            next(self.filter_freq_maker) for i in duration_per_event
        )
        filter_q_per_event = tuple(
            next(self.filter_q_maker) for i in duration_per_event
        )

        rm_freq_per_event = tuple(next(self.rm_freq_maker) for i in duration_per_event)

        transpo_per_event = tuple(next(self.transpo_maker) for i in duration_per_event)

        chenlee_chaos_per_event = tuple(
            next(self.chenlee_chaos_maker) for i in duration_per_event
        )
        chenlee_pitch_per_event = tuple(
            next(self.chenlee_pitch_maker) for i in duration_per_event
        )

        lorenz_chaos_per_event = tuple(
            next(self.lorenz_chaos_maker) for i in duration_per_event
        )
        lorenz_pitch_per_event = tuple(
            next(self.lorenz_pitch_maker) for i in duration_per_event
        )

        ################################################################

        e = synthesis.pyo.Events(
            instr=SlicePlayer,
            path=sample_path_per_event,
            dur=duration_per_event,
            lv=event_lv,
            filter_freq=filter_freq_per_event,
            filter_q=filter_q_per_event,
            rm_freq=rm_freq_per_event,
            h_transpo=transpo_per_event,
            chenlee_chaos=chenlee_chaos_per_event,
            chenlee_pitch=chenlee_pitch_per_event,
            lorenz_chaos=lorenz_chaos_per_event,
            lorenz_pitch=lorenz_pitch_per_event,
            ambient_noise_lv=ambient_noise_lv_per_event,
            **lv_per_effect,
        )
        e.play()

        self.server.start()


class Sampler(synthesis.PyoEngine):
    init_args = {"volume": 1, "skip_n_seconds": 0, "fadein": 0, "fadeout": 0}

    def __init__(
        self, path: str, duration: float = None, loops: float = None, **kwargs
    ):
        if duration is None or loops is not None:
            duration = synthesis.pyo.sndinfo(path)[1]

        if loops is not None:
            duration *= loops

        super().__init__()
        self.__path = path
        self.__duration = duration

        for arg in self.init_args:
            if arg not in kwargs:
                kwargs.update({arg: self.init_args[arg]})

        self.__init_args = kwargs

    @property
    def duration(self) -> float:
        return self.__duration

    @property
    def path(self) -> str:
        return self.__path

    def copy(self) -> "Sampler":
        return type(self)(self.path, self.duration, **self.__init_args)

    def render(self, name: str) -> None:
        self.server.recordOptions(
            dur=self.duration, filename="{}.wav".format(name), sampletype=4
        )

        soundfile = synthesis.pyo.SndTable(self.path)
        osc = synthesis.pyo.Osc(
            soundfile,
            freq=soundfile.getRate(),
            interp=4,
            mul=self.__init_args["volume"],
        )
        osc.out()

        self.server.start()
