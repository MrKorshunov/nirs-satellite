"""Check and export actual Basilisk power-node and battery time series."""
from __future__ import annotations
import csv
import json
from pathlib import Path
import numpy as np


def analyse_run(*, times, components, output: Path):
    ts=np.asarray(times,dtype=float)
    data={
        "shadow":np.asarray(components.eclipse_rec.shadowFactor,dtype=float),
        "panel_w":np.asarray(components.panel_rec.netPower,dtype=float),
        "base_w":np.asarray(components.base_rec.netPower,dtype=float),
        "imaging_w":np.asarray(components.imaging_rec.netPower,dtype=float),
        "transmitter_w":np.asarray(components.transmitter_rec.netPower,dtype=float),
        "battery_j":np.asarray(components.battery_rec.storageLevel,dtype=float),
        "net_w":np.asarray(components.battery_rec.currentNetPower,dtype=float),
    }
    for name,x in data.items():
        if x.shape!=(len(ts),) or not np.all(np.isfinite(x)):
            raise AssertionError(f"Power recorder {name} does not align with orbit samples")
    for rec in (components.eclipse_rec, components.panel_rec, components.base_rec,
                components.imaging_rec, components.transmitter_rec,components.battery_rec):
        rec_t=np.asarray(rec.times(),dtype=float)*1e-9
        if rec_t.shape!=ts.shape or not np.allclose(rec_t,ts,rtol=0,atol=1e-9):
            raise AssertionError("Basilisk power records and spacecraft clock differ")
    capacity=float(components.config["battery_capacity_wh"])*3600.0
    battery=data["battery_j"]
    if np.min(battery) < -1e-3 or np.max(battery)>capacity+1e-3:
        raise AssertionError("Basilisk battery exceeded its declared capacity")
    if np.any(data["panel_w"] < -1e-8):
        raise AssertionError("Basilisk solar panel produced negative electrical output")
    if np.any(data["base_w"]>0.001) or np.any(data["imaging_w"]>0.001):
        raise AssertionError("Electrical loads produced energy")
    if np.min(data["shadow"]) < -0.001 or np.max(data["shadow"])>1.001:
        raise AssertionError("Basilisk eclipse factor outside [0,1]")
    if np.max(np.abs((data["panel_w"]+data["base_w"]+
                     data["imaging_w"]+data["transmitter_w"])-data["net_w"]))>1e-5:
        raise AssertionError("Basilisk battery netPower does not match connected modules")
    solar_wh = float(np.trapezoid(data["panel_w"],ts)/3600)
    used_wh = float(-np.trapezoid(
        data["base_w"]+data["imaging_w"]+data["transmitter_w"],ts)/3600)
    result={
        "model":"Basilisk Eclipse, SimpleSolarPanel, SimplePowerSink, SimpleBattery",
        "samples":len(ts),
        "initial_battery_wh":float(battery[0]/3600),
        "final_battery_wh":float(battery[-1]/3600),
        "minimum_battery_wh":float(np.min(battery)/3600),
        "maximum_battery_wh":float(np.max(battery)/3600),
        "battery_capacity_wh":capacity/3600,
        "max_panel_power_w":float(np.max(data["panel_w"])),
        "solar_energy_wh":solar_wh,
        "used_energy_wh":used_wh,
        "min_sun_fraction":float(np.min(data["shadow"])),
        "max_sun_fraction":float(np.max(data["shadow"])),
        "eclipse_sample_count":int(np.sum(data["shadow"]<0.99)),
        "checks_passed":True,
        "limitations":[
            "Basilisk dynamic first-order power model with FIXED SYNTHETIC Sun direction",
            "Fixed body-mounted panels and constant base load",
            "When Mission01 is enabled, imaging and radio loads are ON for the full run (conservative upper bound)",
            "Imager/radio load profiles are not yet driven by actual device activity; no false DeviceCmd-to-DeviceStatus conversion",
            "Battery low-charge does NOT yet suppress imaging or radio operations",
            "No thermal/power bus, deployment, degradation or voltage losses"
        ],
    }
    output.mkdir(parents=True,exist_ok=True)
    (output/"power_summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    with (output/"power_states.csv").open("w",newline="",encoding="utf-8") as f:
        writer=csv.writer(f)
        writer.writerow(["time_s","sun_fraction","panel_w","base_w","imager_w",
                         "transmitter_w","net_w","battery_wh"])
        for i,t in enumerate(ts):
            writer.writerow([float(t),*[float(data[k][i]) for k in (
                "shadow","panel_w","base_w","imaging_w","transmitter_w","net_w")],
                float(battery[i]/3600)])
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(9,4))
    ax.plot(ts/60,battery/3600,label="Basilisk battery (Wh)")
    ax.plot(ts/60,data["panel_w"],label="Solar power (W)")
    ax.plot(ts/60,data["net_w"],label="Net bus power (W)")
    ax.set(xlabel="Elapsed synthetic time (min)",title="Basilisk Power 01: eclipse, panel and battery")
    ax.grid(alpha=.3);ax.legend();fig.tight_layout()
    fig.savefig(output/"power_states.png",dpi=150);plt.close(fig)
    return result
