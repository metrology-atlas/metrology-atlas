"""One-off import (17 October 2026): signals, devices, clocks and timing forms from the time-source table.

Source: vitaldb-bench/tools/time_source_accuracy_figure.py (ENTRIES, the accuracy and resolution figure) and the
clock domains of vitaldb-bench/tools/pair_timing_budget.py. After this import the YAML files are the source of
truth; this script is kept as the record of where the first numbers came from. It never overwrites a file.

    python datasets/vitaldb/_import/time_sources.py <path to vitaldb-bench/tools>
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, sys.argv[1])
from time_source_accuracy_figure import ENTRIES

D = Path(__file__).resolve().parents[1]

# entry -> clock domain (dataset.yaml domains)
DOMAIN = {
    "snu_model": "reference", "pleth": "reference", "bis_sync": "reference", "primus_sync": "reference",
    "cardioq_sync": "reference", "ev1000_sync": "reference", "snu_raw": "snuadc-raw",
    "bis_raw": "bis", "bis_num": "bis", "primus_raw": "primus", "primus_num": "primus", "primus_lab": "primus",
    "solar_win": "solar8000", "solar_lab": "solar8000", "hr_early": "solar8000", "hr_late": "solar8000",
    "hr_lab": "solar8000", "pleth_hr": "solar8000", "spo2": "solar8000", "nibp": "solar8000",
    "cardioq_raw": "cardioq", "ev1000": "ev1000", "vigileo": "vigileo", "vigilance": "vigilance",
    "invos_fms": "invos-fms", "pumps": "pumps", "caseend": "records", "lab_bg": "records",
    "lab_central": "records", "lab_draw": "records", "emr1": "records", "emr5": "records", "admdis": "records",
}

# signal id -> (name, device, type, source name, stamp clock, sample clock, rate, unit, [(entry, form name, default)], summary)
SIGNALS = {
    "snuadc-ecg-ii": None,  # exists; only timing is added
    "snuadc-art": ("Arterial pressure (SNUADC)", "snuadc", "waveform", "SNUADC/ART", "recorder-pc", "snuadc-sample",
                   500, "mmHg", [("snu_model", "stamp-model time", True), ("snu_raw", "raw stamps", False)],
                   "Invasive arterial pressure, sampled by SNUADC at 500 Hz from the monitor's analogue output."),
    "snuadc-pleth": ("Plethysmogram (SNUADC)", "snuadc", "waveform", "SNUADC/PLETH", "recorder-pc", "snuadc-sample",
                     500, "", [("pleth", "stamp-model time", True)],
                     "The pulse oximeter's plethysmogram, sampled by SNUADC at 500 Hz. It reaches SNUADC through the "
                     "oximeter's own 30 Hz frame clock and a hardware delay of about 0.4 s."),
    "bis-eeg": ("BIS EEG", "bis", "waveform", "BIS/EEG1_WAV", "recorder-pc", "bis-clock", 128, "uV",
                [("bis_sync", "after sync to the ECG", True), ("bis_raw", "raw stamps", False)],
                "The raw EEG from the BIS monitor at 128 Hz."),
    "bis-index": ("BIS index", "bis", "numeric", "BIS/BIS", "bis-clock", None, None, "",
                  [("bis_num", "as stamped", True)], "The BIS depth-of-anaesthesia index, computed from a window of EEG."),
    "primus-awp": ("Airway pressure (Primus)", "primus", "waveform", "Primus/AWP", "recorder-pc", "primus-clock", 62.5,
                   "hPa", [("primus_sync", "after breath matching", True), ("primus_raw", "raw stamps", False)],
                   "Airway pressure from the Primus anaesthesia machine at 62.5 Hz."),
    "primus-co2": ("Capnogram (Primus)", "primus", "waveform", "Primus/CO2", "recorder-pc", "primus-clock", 62.5, "mmHg",
                   [("primus_sync", "after breath matching", True), ("primus_raw", "raw stamps", False)],
                   "Sidestream CO2 from the Primus at 62.5 Hz; the sampling line adds at least 1 s."),
    "primus-numerics": ("Primus ETCO2, PIP and RR", "primus", "numeric", "Primus/ETCO2", "recorder-pc", None, None, "",
                        [("primus_lab", "after the per-case delay label", True), ("primus_num", "as stamped", False)],
                        "End-tidal CO2, peak pressure and respiratory rate from the Primus, polled about every 7 s."),
    "solar8000-art-numerics": ("Solar8000 ART and CVP numerics", "solar8000", "numeric", "Solar8000/ART_MBP",
                               "recorder-pc", None, None, "mmHg",
                               [("solar_lab", "after the per-case delay label", True), ("solar_win", "as stamped", False)],
                               "Arterial and central venous pressure values from the Solar8000 monitor."),
    "solar8000-hr": ("Solar8000 heart rate", "solar8000", "numeric", "Solar8000/HR", "recorder-pc", None, None, "/min",
                     [("hr_lab", "after the per-case delay label", True), ("hr_early", "as stamped, early group", False),
                      ("hr_late", "as stamped, late group", False)],
                     "Heart rate from the Solar8000, in one of two delay groups per case."),
    "solar8000-pleth-hr": ("Solar8000 pulse rate (PLETH_HR)", "solar8000", "numeric", "Solar8000/PLETH_HR",
                           "recorder-pc", None, None, "/min", [("pleth_hr", "as stamped", True)],
                           "Pulse rate from the oximeter, over about 12 beats."),
    "solar8000-spo2": ("SpO2", "solar8000", "numeric", "Solar8000/PLETH_SPO2", "recorder-pc", None, None, "%",
                       [("spo2", "as stamped", True)], "Oxygen saturation from the pulse oximeter."),
    "solar8000-nibp": ("Non-invasive blood pressure", "solar8000", "numeric", "Solar8000/NIBP_MBP", "recorder-pc", None,
                       None, "mmHg", [("nibp", "as stamped", True)], "Cuff blood pressure, recorded after each cuff cycle."),
    "cardioq-abp": ("CardioQ pressure and flow", "cardioq", "waveform", "CardioQ/ABP", "recorder-pc", "cardioq-clock",
                    180, "", [("cardioq_sync", "after beat matching", True), ("cardioq_raw", "raw stamps", False)],
                    "Arterial pressure and aortic flow waveforms from the CardioQ oesophageal Doppler monitor."),
    "ev1000-art-mbp": ("EV1000 mean arterial pressure", "ev1000", "numeric", "EV1000/ART_MBP", "recorder-pc", None, None,
                       "mmHg", [("ev1000_sync", "after MAP alignment", True), ("ev1000", "as stamped", False)],
                       "Mean arterial pressure from the EV1000 platform, updated every 20 s."),
    "vigileo-sv": ("Vigileo SV, CO and SVV", "vigileo", "numeric", "Vigileo/SV", "recorder-pc", None, None, "",
                   [("vigileo", "as stamped", True)], "Stroke volume, cardiac output and stroke volume variation."),
    "vigilance-co": ("Vigilance continuous cardiac output", "vigilance", "numeric", "Vigilance/CO", "recorder-pc", None,
                     None, "L/min", [("vigilance", "as stamped", True)], "Continuous cardiac output and averaged HR."),
    "invos-rso2": ("Invos regional oxygen saturation", "invos", "numeric", "Invos/SCO2_L", "recorder-pc", None, None, "%",
                   [("invos_fms", "as stamped", True)], "Cerebral oximetry; no signal shared with the reference."),
    "fms-infusion": ("FMS rapid infuser", "fms", "numeric", "FMS/FLOW_RATE", "recorder-pc", None, None, "",
                     [("invos_fms", "as stamped", True)], "Rapid infuser flow and volume."),
    "pump-rates": ("Infusion pump rates and volumes", "orchestra", "numeric", "Orchestra/PPF20_RATE", "recorder-pc",
                   None, None, "", [("pumps", "as stamped", True)], "Drug infusion rates and volumes from the pumps."),
    "case-end": ("Case end", "clinical-records", "event", "caseend", "hospital-records", None, None, "",
                 [("caseend", "as recorded", True)], "The end of the recording in the clinical table."),
    "lab-blood-gas": ("Blood gas result time", "clinical-records", "event", "lab_data (blood gas)", "hospital-records",
                      None, None, "", [("lab_bg", "lab timestamp", True), ("lab_draw", "draw time from arterial access", False)],
                      "Time stamp of a blood gas result in the lab table."),
    "lab-central": ("Central lab result time", "clinical-records", "event", "lab_data (central lab)", "hospital-records",
                    None, None, "", [("lab_central", "lab timestamp", True), ("lab_draw", "draw time from arterial access", False)],
                    "Time stamp of a central laboratory result in the lab table."),
    "emr-events": ("Anaesthesia record events", "clinical-records", "event", "clinical_data times", "hospital-records",
                   None, None, "", [("emr5", "5-minute entries", True), ("emr1", "minute entries", False)],
                   "Anaesthesia and operation start and end times in the clinical table."),
    "admission-discharge": ("Admission and discharge", "clinical-records", "event", "adm, dis", "hospital-records", None,
                            None, "", [("admdis", "as recorded", True)], "Hospital admission and discharge, in days."),
}

DEVICES = {
    "bis": ("BIS monitor", "monitor", ["bis-clock"], "Medtronic BIS: raw EEG at 128 Hz and the BIS index."),
    "primus": ("Primus anaesthesia machine", "ventilator", ["primus-clock"],
               "Dräger Primus: airway pressure and CO2 waveforms at 62.5 Hz and ventilation numerics."),
    "solar8000": ("Solar8000 monitor", "monitor", ["solar8000-clock"],
                  "GE Solar 8000M patient monitor: numerics (HR, pressures, SpO2, NIBP) and the analogue outputs SNUADC samples."),
    "cardioq": ("CardioQ", "monitor", ["cardioq-clock"], "Deltex CardioQ oesophageal Doppler: pressure and flow waveforms."),
    "ev1000": ("EV1000", "monitor", [], "Edwards EV1000 haemodynamic platform."),
    "vigileo": ("Vigileo", "monitor", [], "Edwards Vigileo: SV, CO and SVV."),
    "vigilance": ("Vigilance", "monitor", [], "Edwards Vigilance: continuous cardiac output."),
    "invos": ("Invos", "monitor", [], "Medtronic Invos cerebral oximeter."),
    "fms": ("FMS rapid infuser", "other", [], "Belmont FMS 2000 rapid infuser."),
    "orchestra": ("Infusion pumps", "other", [], "Fresenius Orchestra infusion pumps."),
    "clinical-records": ("Clinical records", "other", ["hospital-records"],
                         "The clinical table and lab table of the release: anaesthesia record, lab results, admission."),
}

CLOCKS = {
    "bis-clock": ("BIS clock", "oscillator", "128 Hz EEG sample clock",
                  "The BIS monitor's own clock. Its EEG stamps drift by about +23 ppm against the recorder PC and are "
                  "corrected on a fixed 8,192 s timer."),
    "primus-clock": ("Primus clock", "oscillator", "62.5 Hz waveform clock",
                     "The Primus anaesthesia machine's own clock. Its stamps are re-anchored at recording gaps and by "
                     "small corrections about every two hours; its drift is not yet well measured."),
    "solar8000-clock": ("Solar8000 clock", "unknown", "Monitor numerics windows",
                        "The Solar8000 monitor's internal timing of its numeric windows. The values are stamped by the "
                        "recorder on arrival, so only their delay is seen."),
    "cardioq-clock": ("CardioQ clock", "oscillator", "Waveform sample clock",
                      "The CardioQ's own clock; the recorder re-anchors its stamps about every 5 minutes."),
    "hospital-records": ("Hospital records clock", "software", "Clinical and laboratory systems",
                         "The clocks of the anaesthesia record and the laboratory system, and the rounding of what was "
                         "entered. Not observable in the release except through events seen in the signals."),
}


def write(path: Path, item: dict) -> None:
    """Write a generated item as YAML, unless the file already exists."""
    if path.exists():
        return
    path.write_text(yaml.safe_dump(item, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")


def form(entry: str, name: str, default: bool) -> dict:
    """One timing form of a variable (delay and interval ranges, clock domain) from the time-source table."""
    e = ENTRIES[entry]
    f = {"id": entry.replace("_", "-"), "name": name}
    if default:
        f["default"] = True
    f.update({"delay_s": [e[2], e[3]], "interval_s": [e[4], e[5]], "domain": DOMAIN[entry],
              "status": "measured" if e[6] else "assumed", "evidence": e[9]})
    return f


for cid, (name, typ, nominal, desc) in CLOCKS.items():
    write(D / "clocks" / f"{cid}.yaml", {"id": cid, "name": name, "summary": desc.split(". ")[0] + ".", "type": typ,
                                         "nominal": nominal, "description": desc, "tags": ["stub"]})
for did, (name, typ, clocks, summary) in DEVICES.items():
    item = {"id": did, "name": name, "summary": summary, "type": typ}
    if clocks:
        item["clocks"] = clocks
    item["tags"] = ["stub"]
    write(D / "devices" / f"{did}.yaml", item)
for sid, spec in SIGNALS.items():
    path = D / "variables" / f"{sid}.yaml"
    if spec is None:
        item = yaml.safe_load(path.read_text(encoding="utf-8"))
        if "timing" not in item:
            item["timing"] = [form("snu_model", "stamp-model time", True), form("snu_raw", "raw stamps", False)]
            path.write_text(yaml.safe_dump(item, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
        continue
    name, dev, typ, src, stamp, sample, rate, unit, forms, summary = spec
    item = {"id": sid, "name": name, "summary": summary, "type": typ, "source_name": src, "device": dev,
            "stamp_clock": stamp}
    if sample:
        item["sample_clock"] = sample
    if rate:
        item["rate_hz"] = rate
    if unit:
        item["unit"] = unit
    item["timing"] = [form(*f) for f in forms]
    item["tags"] = ["stub"]
    write(path, item)
print("done")
