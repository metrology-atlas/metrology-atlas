"""The atlas's schema: which kinds of item exist, which fields each has, and how they refer to each other.

Nothing here is specific to one dataset. A dataset is a folder of YAML files, one per item, in a sub-folder per
kind (``clocks/``, ``devices/`` ...), plus ``dataset.yaml`` and ``references.yaml``.

Relations are written once, on one side, and the other side is derived:

- a signal names its device and its clocks; a device's page lists its signals;
- a parameter names the study that produced it and the items it is about; a study's page lists its parameters;
- a link names the two clocks it relates; each clock's page lists its links.

Prose fields are Markdown. ``[[kind:id]]`` inside prose is a cross-reference, checked like any other reference.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA_VERSION = "metrology-atlas/0.2"


@dataclass(frozen=True)
class Field:
    """One field of an item."""

    name: str
    type: str
    """``str``, ``text`` (Markdown), ``number``, ``ints``, ``bool``, ``range`` (two numbers, low and high), ``date``, ``enum``,
    ``ref``, ``refs``, ``strs``, ``obj``, ``objs``."""
    required: bool = False
    ref: str | tuple[str, ...] = ()
    """For ``ref``/``refs``: the kind or kinds referred to; empty means any kind."""
    choices: tuple[str, ...] = ()
    fields: tuple[Field, ...] = ()
    """For ``obj``/``objs``: the nested fields."""
    help: str = ""


@dataclass(frozen=True)
class Kind:
    """One kind of item."""

    name: str
    folder: str
    title: str
    """Plural, for headings and navigation."""
    fields: tuple[Field, ...]
    help: str = ""

    def field(self, name: str) -> Field | None:
        return next((f for f in self.fields if f.name == name), None)


STATUS = ("measured", "derived", "estimated", "assumed", "withdrawn", "superseded")
OBS_STATUS = ("established", "likely", "open", "withdrawn")
STUDY_STATUS = ("current", "draft", "open", "superseded", "withdrawn")
ANCHOR_BASIS = ("tested", "convention", "assumption", "open")

FIGURE = (
    Field("id", "str", required=True, help="Unique within its item; [[figure:id]] in the item's prose places it."),
    Field("file", "str", required=True, help="A file in the dataset's figures/ folder."),
    Field("caption", "text", required=True),
    Field("alt", "str", required=True, help="What the figure shows, for readers who cannot see it."),
    Field("study", "ref", ref="study", help="The study the figure comes from."),
    Field("placeholder", "bool", help="Shown with a note that a final figure will replace it."),
    Field("interactive", "bool", help="An SVG whose links should work: embedded as an object, not an image."),
    Field("theme", "str", help="Figure family for the gallery, e.g. 'drift and resets', 'delay and window fits'."),
    Field("source", "str", help="Script and output file the figure came from (for reproduction)."),
    Field("records", "ints", help="Record ids (e.g. VitalDB cases) the figure shows, for figures of specific examples."),
)

QUESTION_KINDS = ("phenomenon", "hypothesis", "assumption", "conflict", "next step")
QUESTION_KIND_TITLES = {
    "phenomenon": "Unexplained phenomena",
    "hypothesis": "Weakly supported hypotheses",
    "assumption": "Untestable assumptions",
    "conflict": "Conflicts between studies",
    "next step": "Unfinished checks and decisions",
}
QUESTION = (
    Field("title", "str", required=True, help="A short name for the question."),
    Field("kind", "enum", required=True, choices=QUESTION_KINDS,
          help="phenomenon: seen but unexplained; hypothesis: an explanation the evidence only weakly supports; "
               "assumption: relied on but not testable with the data; conflict: two studies disagree; "
               "next step: a planned check or a pending decision (kept on the study page, not in the public list)."),
    Field("summary", "text", required=True, help="What is seen, why it matters and, where known, what would settle it."),
)

COMMON = (
    Field("id", "str", required=True, help="Unique within its kind; equals the file name without .yaml."),
    Field("name", "str", required=True),
    Field("summary", "str", required=True, help="One or two sentences, shown in lists and at the top of the page."),
    Field("description", "text"),
    Field("references", "refs", ref="reference"),
    Field("tags", "strs"),
    Field("figures", "objs", fields=FIGURE),
)

VALUE = (
    Field("kind", "str", help="The value model's kind, e.g. single_resolution, heaped, mixed_source, derived, exact."),
    Field("resolution", "str", help="Value resolution in words, e.g. '1 cm, often heaped to 5 cm'."),
    Field("step", "number", help="Native resolution step, in the variable's unit."),
    Field("anchor", "enum", choices=("nearest", "floor", "ceiling"), help="How the true value is rounded to the step."),
    Field("anchor_basis", "enum", choices=ANCHOR_BASIS,
          help="How the anchor (or, for a count, its counting rule) is known: tested on the data, a convention whose "
               "effect is negligible, an assumption the data cannot test, or open. Unset means the dataset's "
               "anchor_default applies."),
    Field("anchor_note", "text", help="Why: the evidence, the convention, or what would settle it."),
    Field("accuracy", "text", help="Instrument or method error: how far the true value can be from the recorded one "
                                   "beyond resolution."),
    Field("accuracy_sd", "number", help="Accuracy as one standard deviation, in the variable's unit, when known."),
    Field("model", "str", help="Code reference (software-id/path) of a value model; read from the dataset's "
                               "pinned snapshot of that software."),
    Field("inputs", "refs", ref="variable", help="For a derived value: the variables it is computed from."),
    Field("formula", "str", help="For a derived value: how it is computed from its inputs."),
    Field("combination", "str", help="For a derived value: how the inputs' uncertainties are combined."),
    Field("spread", "str", help="Aggregate width of the true-value distributions in the release: "
                                "'software-id/path.json#key', read from the pinned snapshot."),
    Field("status", "enum", choices=STATUS),
    Field("studies", "refs", ref="study"),
)

MODE = (Field("id", "str", required=True), Field("name", "str", required=True), Field("description", "text"))
TIMING = (
    Field("id", "str", required=True),
    Field("name", "str", required=True, help="Which form of the times this is, e.g. 'raw stamps' or 'after sync'."),
    Field("default", "bool", help="The form an analysis should use; one per signal."),
    Field("delay_s", "range", required=True,
          help="Delay from the end of the interval a value describes to its stamp, against the working reference: "
               "[low, high] in seconds. Corrected to the middle, what is left is the spread."),
    Field("interval_s", "range", required=True,
          help="Width of the interval one value or sample stands for: [low, high] in seconds."),
    Field("corrected_delay_s", "range",
          help="When this form is a correction (a per-case label, a sync to the reference): the delay it removes, "
               "[low, high] s. `delay_s` is then what is left after it, and the correction, not a fixed shift, "
               "lines the signal up. Counts towards latency: the data was still only available that late."),
    Field("correction", "str", help="What the correction is, in a few words."),
    Field("corrects", "strs", help="Ids of this signal's other forms that this one improves on (drawn as arrows)."),
    Field("domain", "str", required=True, help="Clock domain (dataset.yaml `domains`) whose drift remains."),
    Field("status", "enum", required=True, choices=STATUS),
    Field("evidence", "str", required=True, help="Where the numbers come from, in a line."),
    Field("studies", "refs", ref="study"),
)

STEP = (
    Field("node", "str", required=True, help="The stage this step reaches, e.g. 'Recorder PC clock' or 'Stored stamp'."),
    Field("clock", "ref", ref="clock", help="The clock at that stage, if it is one."),
    Field("kind", "enum", required=True,
          choices=("sync", "clock", "stamping", "transport", "processing", "window", "correction")),
    Field("effect", "text", required=True, help="What happens to the time at this step, in a sentence or two."),
    Field("offset_s", "range", help="Size of the time shift or error this step introduces: [low, high] s."),
    Field("residual_s", "range", help="What is left of it after the atlas's correction: [low, high] s."),
    Field("drift", "str", help="Drift at this step, in words, e.g. '−62 ppm, pulled back every ~2 h'."),
    Field("status", "enum", required=True, choices=STATUS),
    Field("link", "ref", ref="link"),
    Field("parameter", "ref", ref="parameter"),
    Field("studies", "refs", ref="study"),
)

DELAY = (
    Field("name", "str", required=True),
    Field("parameter", "ref", ref="parameter"),
    Field("description", "text"),
)

KINDS: dict[str, Kind] = {
    k.name: k
    for k in (
        Kind(
            "clock", "clocks", "Clocks",
            COMMON + (
                Field("type", "enum", required=True,
                      choices=("oscillator", "software", "physiological", "derived", "reference", "unknown")),
                Field("nominal", "str", help="What the clock is meant to count, e.g. '500 Hz sample clock'."),
                Field("modes", "objs", fields=MODE, help="Distinct behaviours of one clock."),
                Field("utc_plan", "text",
                      help="How this clock is, or will be, traced back to UTC: what is measured, what is assumed, "
                           "and what would close the gaps. Shown with the route the atlas finds through its links."),
            ),
            help="Anything that keeps time: a crystal, a computer clock, a frame clock, a pacemaker.",
        ),
        Kind(
            "device", "devices", "Devices",
            COMMON + (
                Field("type", "enum", required=True,
                      choices=("acquisition", "monitor", "recorder", "ventilator", "implant", "software", "other")),
                Field("clocks", "refs", ref="clock", help="The clocks this device runs on or keeps."),
                Field("manufacturer", "str"),
                Field("model", "str"),
                Field("docs", "objs", fields=(
                    Field("title", "str", required=True), Field("url", "str", required=True),
                ), help="Manufacturer or VitalDB pages about the device (links, not references)."),
                Field("tracks", "objs", fields=(
                    Field("track", "str", required=True, help="Track name in the file, without the device prefix."),
                    Field("kind", "enum", required=True, choices=("waveform", "numeric")),
                    Field("unit", "str"),
                    Field("format", "str", help="Storage format (uint16, float32 ...)."),
                    Field("rate", "str", help="Sample rate (waveforms) or median interval between records (numerics)."),
                    Field("gain", "number"), Field("offset", "number"),
                    Field("recordings", "number", help="Recordings stored with this gain and offset."),
                    Field("corrected_gain", "number"), Field("corrected_offset", "number"),
                    Field("correction", "text", help="Why the stored factors are wrong, with a link to the evidence."),
                    Field("step", "str", help="Step between stored values, in the physical unit."),
                    Field("span", "str", help="Observed span: lowest to highest code reached, and codes used."),
                    Field("bits_to_store", "number", help="Whole bits needed to store the observed span."),
                    Field("converter", "str", help="Estimated converter resolution (never less than the span)."),
                    Field("evidence", "text", help="Evidence for the converter estimate."),
                    Field("grid", "number", help="Numerics: the coarsest decimal grid holding 99% of records."),
                    Field("coarser_share", "number", help="Numerics: share of records on the next coarser grid."),
                    Field("rounding", "str", help="round / truncate / unknown, with its status."),
                    Field("range", "str", help="Observed range of physical values (corrupt values noted separately)."),
                    Field("note", "text"),
                ), help="Scale factors and resolution of each track, one entry per stored configuration; usually "
                        "generated by _import/device_tracks.py."),
            ),
            help="Hardware or software that produces signals.",
        ),
        Kind(
            "variable", "variables", "Variables",
            COMMON + (
                Field("type", "enum", required=True,
                      choices=("waveform", "numeric", "event", "text", "clinical", "lab", "time")),
                Field("measurand", "text", help="What the true quantity is: what a perfect record of this variable "
                                                "would hold (for a numeric, the value over its window, not at its stamp)."),
                Field("source", "str", help="Where the dataset stores it: a file, table or track group."),
                Field("group", "str", help="Where it is listed: 'Group', under the section its type implies, or "
                                           "'Section/Group' to choose the section too."),
                Field("device", "ref", ref="device"),
                Field("stamp_clock", "ref", ref="clock",
                      help="The clock whose time stamps the stored values carry (leave out for values with no time)."),
                Field("sample_clock", "ref", ref="clock",
                      help="The clock that spaces the samples, when it is not the stamping clock."),
                Field("source_name", "str", help="The signal's name in the dataset, e.g. a track name."),
                Field("rate_hz", "number"),
                Field("unit", "str"),
                Field("delays", "objs", fields=DELAY, help="Lags between an event and its stamp."),
                Field("window", "obj", fields=DELAY, help="The span of time a value summarises."),
                Field("chain", "objs", fields=STEP,
                      help="Every step from UTC to this signal's stored time stamp, in order. Drawn on the page. "
                           "The dataset's UTC step comes first, unless the chain starts with its own sync step."),
                Field("timing", "objs", fields=TIMING,
                      help="How well this signal's times line up with the working reference, in each form "
                           "they come in (raw, after a correction ...). Read by the synchronisation planner."),
                Field("value", "obj", fields=VALUE, help="The value side: what the recorded number says about the true one."),
                Field("coupling", "obj", fields=(
                    Field("status", "enum", required=True, choices=("independent", "coupled", "unknown")),
                    Field("note", "text"),
                ), help="Whether the time error and the value error are independent, and why not when they are not."),
            ),
            help="Every recorded quantity: a waveform, a numeric, an event, a clinical field, a lab result. Each is "
                 "described on two axes, time and value, each with its accuracy and its resolution.",
        ),
        Kind(
            "link", "links", "Clock links",
            COMMON + (
                Field("clock", "ref", required=True, ref="clock", help="The clock described."),
                Field("against", "ref", required=True, ref="clock", help="The clock it is measured against."),
                Field("modes", "strs", help="Mode ids of `clock` this link applies to; empty for all."),
                Field("rate", "ref", ref="parameter", help="Drift of `clock` against `against`, in ppm."),
                Field("correction", "obj", fields=(
                    Field("rule", "text", required=True),
                    Field("period", "ref", ref="parameter"),
                    Field("size", "ref", ref="parameter"),
                )),
                Field("status", "enum", required=True, choices=STATUS),
            ),
            help="How one clock relates to another: drift and correction. Every rate is relative to `against`.",
        ),
        Kind(
            "parameter", "parameters", "Parameters",
            (
                Field("id", "str", required=True),
                Field("name", "str", required=True),
                Field("quantity", "str", required=True, help="What is measured, in words."),
                Field("value", "number"),
                Field("unit", "str"),
                Field("spread", "obj", fields=(
                    Field("p10", "number"), Field("p90", "number"), Field("q1", "number"), Field("q3", "number"),
                    Field("sd", "number"), Field("min", "number"), Field("max", "number"), Field("n", "number"),
                    Field("text", "str"),
                )),
                Field("display", "str", help="How to show the value when numbers alone do not say it."),
                Field("status", "enum", required=True, choices=STATUS),
                Field("study", "ref", ref="study", help="The study that produced it (not needed when assumed)."),
                Field("about", "refs", ref=("clock", "device", "variable", "link", "observation"), required=True),
                Field("superseded_by", "ref", ref="parameter"),
                Field("date", "date"),
                Field("notes", "text"),
                Field("headline", "bool", help="Show on the home page among the key numbers."),
                Field("setup_key", "str", help="What a setup is for this parameter's per-setup values, e.g. 'PC key'."),
                Field("by_setup", "objs", fields=(
                    Field("setup", "str", required=True),
                    Field("value", "number", required=True),
                    Field("q1", "number"), Field("q3", "number"),
                    Field("n", "number"),
                    Field("note", "str"),
                ), help="The parameter per recording setup, where it is known per setup (see the Recording setups page)."),
            ),
            help="One number the atlas relies on, with its uncertainty and where it came from.",
        ),
        Kind(
            "study", "studies", "Studies",
            COMMON + (
                Field("date", "date", required=True),
                Field("status", "enum", required=True, choices=STUDY_STATUS),
                Field("methods", "refs", required=True, ref="method"),
                Field("techniques", "refs", ref="technique"),
                Field("clocks", "refs", ref="clock"),
                Field("devices", "refs", ref="device"),
                Field("variables", "refs", ref="variable"),
                Field("data", "text", help="What data the study used, in aggregate (never record identifiers)."),
                Field("background", "text"),
                Field("method", "text"),
                Field("results", "text"),
                Field("discussion", "text"),
                Field("limitations", "text"),
                Field("open_questions", "objs", fields=QUESTION,
                      help="What the study left open, one entry per question, each with its kind."),
                Field("code", "strs", help="Scripts or modules as software-id/path (path inside that repository); "
                                           "software-id alone names the whole repository."),
                Field("model", "str", help="Code reference of the model this study fitted; its numbers are read "
                                           "from the dataset's pinned snapshot, never copied."),
                Field("supersedes", "refs", ref="study"),
            ),
            help="One piece of work that produced insight: a mini report.",
        ),
        Kind(
            "observation", "observations", "Observations",
            COMMON + (
                Field("status", "enum", required=True, choices=OBS_STATUS),
                Field("clocks", "refs", ref="clock"),
                Field("devices", "refs", ref="device"),
                Field("variables", "refs", ref="variable"),
                Field("studies", "refs", ref="study", help="The studies that show it."),
                Field("consequence", "text", help="What it means for someone using the data."),
                Field("handling", "text", help="What the atlas, its tools or its importers do about it."),
                Field("code", "strs", help="Code that handles it: software-id/path."),
                Field("supersedes", "refs", ref="observation"),
            ),
            help="A general fact about the dataset's timing or recording, with its evidence and what it means.",
        ),
        Kind(
            "method", "methods", "Methods",
            COMMON + (Field("techniques", "refs", ref="technique"),
                      Field("order", "number", help="Position in lists of methods (lowest first).")),
            help="A methodology group: studies that get at timing the same way.",
        ),
        Kind(
            "technique", "techniques", "Techniques",
            COMMON,
            help="A reusable building block that studies share.",
        ),
        Kind(
            "example", "examples", "Worked examples",
            COMMON + (
                Field("side", "enum", required=True, choices=("time", "value", "both"),
                      help="Which side of the measurement the example is about."),
                Field("status", "enum", required=True, choices=("planned", "draft", "current")),
                Field("question", "text", required=True, help="The analysis question, as a user would ask it."),
                Field("why", "text", help="Why the atlas's findings change the answer."),
                Field("variables", "refs", ref="variable", help="The variables it uses."),
                Field("studies", "refs", ref="study", help="The studies whose results it relies on."),
                Field("observations", "refs", ref="observation"),
                Field("data", "text", help="Cases and signals used (aggregates, or named cases for figures)."),
                Field("steps", "text", help="What the code does, step by step."),
                Field("results", "text"),
                Field("takeaways", "text", help="What a reader should do differently in their own analysis."),
                Field("limitations", "text"),
                Field("code", "strs", help="Scripts as software-id/path; the page tells readers how to rerun them."),
                Field("reproduce", "text", help="The commands to rerun it."),
                Field("open_questions", "objs", fields=QUESTION,
                      help="Limitations still open and future work, one entry per question, each with its kind."),
            ),
            help="Common analyses worked through with and without the atlas's corrections, with code to reproduce "
                 "them: where clock alignment or rounding changes the answer.",
        ),
        Kind(
            "software", "software", "Software",
            COMMON + (
                Field("role", "text", help="What part it plays in the atlas's work, in a sentence or two."),
                Field("repo", "str", help="Repository web address; code paths link into it. Leave out when unpublished."),
                Field("branch", "str", help="Branch the links point at (default main)."),
                Field("visibility", "enum", choices=("public", "private", "unpublished")),
                Field("local", "str", help="Path of a local copy, relative to the dataset folder. Only used to check "
                                           "that code paths exist; skipped when the folder is not there."),
                Field("url", "str", help="Home page or package index page."),
                Field("docs", "str", help="Documentation web address."),
                Field("licence", "str"),
                Field("language", "str"),
                Field("install", "text"),
                Field("parts", "objs", fields=(
                    Field("path", "str", required=True, help="A file or folder, relative to the repository root."),
                    Field("name", "str"),
                    Field("summary", "text", required=True),
                    Field("group", "str", help="Heading the part is listed under."),
                ), help="The files and folders worth knowing about."),
                Field("related", "refs", ref="software"),
            ),
            help="The code behind the studies, importers and tools. Code paths in studies link into these repositories.",
        ),
    )
}

REFERENCE = Kind(
    "reference", "", "References",
    (
        Field("id", "str", required=True),
        Field("citation", "str", required=True),
        Field("url", "str"),
        Field("doi", "str"),
        Field("note", "str"),
        Field("group", "str", help="Heading it is listed under on the references page."),
    ),
)


@dataclass
class Dataset:
    """A loaded dataset: its settings and every item by kind and id."""

    meta: dict
    folder: str = ""
    items: dict[str, dict[str, dict]] = field(default_factory=dict)
    """kind -> id -> item (as authored)."""
    sources: dict[tuple[str, str], str] = field(default_factory=dict)
    """(kind, id) -> the file it came from."""
    warnings: list[str] = field(default_factory=list)
    """Things worth fixing that do not stop a build (for example code not yet committed)."""

    def get(self, kind: str, id_: str) -> dict | None:
        return self.items.get(kind, {}).get(id_)


DATASET = (
    Field("id", "str", required=True),
    Field("name", "str", required=True),
    Field("summary", "str", required=True),
    Field("description", "text"),
    Field("overview", "text", help="Shown on the home page under 'System overview'."),
    Field("examples_intro", "text", help="Introduction at the top of the worked examples' index page."),
    Field("notice", "text", help="Shown prominently at the top of the home page, e.g. that the atlas is a work in "
                                 "progress."),
    Field("anchor_default", "obj", fields=(
        Field("basis", "enum", required=True, choices=ANCHOR_BASIS),
        Field("note", "text", required=True),
    ), help="Anchor basis for variables that state an anchor but no anchor_basis."),
    Field("reference", "text", help="What the working reference is; the planner's timings are against it."),
    Field("reference_clock", "ref", ref="clock", help="The clock of the working reference."),
    Field("figures", "objs", fields=FIGURE),
    Field("utc_step", "obj", fields=STEP, help="The first step of every signal's chain: UTC to the dataset's root clock."),
    Field("domains", "objs", fields=(
        Field("id", "str", required=True),
        Field("name", "str", required=True),
        Field("clock", "ref", ref="clock"),
        Field("drift_ppm", "number", help="Drift against the working reference; leave out when unknown."),
        Field("drift_status", "enum", choices=STATUS),
        Field("note", "str"),
    ), help="Clock domains: signals in one domain share their drift, which then cancels between them."),
    Field("sources", "objs", fields=(
        Field("software", "ref", required=True, ref="software"),
        Field("folder", "str", required=True, help="Snapshot folder, relative to the dataset; mirrors the repository."),
        Field("format", "str", help="Which reader understands its model files (default: the software id)."),
        Field("commit", "str"), Field("date", "date"), Field("note", "str"),
    ), help="Pinned snapshots of other software's data files. Read, never edited; refreshed by an import script."),
    Field("references", "refs", ref="reference", help="Shown on the home page: what to cite with the atlas."),
    Field("reference_groups", "strs", help="Order of the groups on the references page."),
    Field("figure_themes", "strs", help="Order of the themes in the figure gallery."),
    Field("variable_groups", "strs", help="Order of the variable groups in lists and navigation (others follow, "
                                           "alphabetically)."),
    Field("pages", "objs", fields=(
        Field("id", "str", required=True, help="Page file name without .md; must not clash with a kind's folder."),
        Field("title", "str", required=True),
        Field("file", "str", required=True, help="A Markdown file in the dataset's pages/ folder; [[kind:id]] works."),
        Field("section", "enum", choices=("Time", "Value", "About"),
              help="Navigation section the page is listed under (default About)."),
    ), help="Free pages (contributing, about ...), listed under About after the atlas's own 'Aim and terms'."),
    Field("site", "obj", fields=(Field("title", "str"), Field("repo_url", "str"), Field("copyright", "str"))),
    Field("records", "obj", fields=(
        Field("name", "str", required=True, help="Word used in references, e.g. 'case' for [[case:1234]]."),
        Field("label", "str", help="How a reference reads, with {id}; default '<name> {id}'."),
        Field("max", "number", help="Highest valid id."),
        Field("url", "str", help="Optional link for one record, with {id}."),
        Field("policy", "text", help="When record ids may be used; shown on the records page."),
    ), help="Individual records (cases) that studies may name. Write them as [[name:id]]; forbidden patterns do not "
            "apply inside such references, so every mention is deliberate and listed."),
    Field("forbidden_patterns", "objs", fields=(Field("pattern", "str", required=True), Field("why", "str"))),
)
