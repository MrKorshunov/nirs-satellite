"""Independent acceptance of true Basilisk multi-target capture/storage/downlink.

No invented image data: events are inferred from Basilisk SimpleInstrument
DataNodeUsageMsg, and physical boresight is re-computed from recorded
Spacecraft inertial pose. A transmitter decrement is NOT ground RX/ACK.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np

from experiments.adcs_01.kinematics import true_boresight_error_deg


def analyse_multi(
    *, output:Path, time_s, position_N_m, target_N_m, sigma_BN,
    target_access, station_access, instrument_bits_s, transmit_bits_s,
    storage_bits, storage_names, storage_partitions, command,
    guidance_sigma, guidance_rate, rw_rpm, battery_wh, target_ids,
    targets, config, power_reserve_wh, events, boresight_B
)->dict:
    t=np.asarray(time_s,dtype=float)
    n=len(t)
    x=np.asarray(position_N_m,dtype=float)
    y=np.asarray(target_N_m,dtype=float)
    sigma=np.asarray(sigma_BN,dtype=float)
    visible=np.asarray(target_access,dtype=bool)
    station=np.asarray(station_access,dtype=bool)
    imager=np.asarray(instrument_bits_s,dtype=float)
    radio=np.asarray(transmit_bits_s,dtype=float)
    memory=np.asarray(storage_bits,dtype=float)
    cmds=np.asarray(command,dtype=int)
    guidance=np.asarray(guidance_sigma,dtype=float)
    rate_error=np.asarray(guidance_rate,dtype=float)
    wheels=np.asarray(rw_rpm,dtype=float)
    energy=np.asarray(battery_wh,dtype=float)
    names=np.asarray(target_ids,dtype=str)
    capacity=8*float(config["storage"]["capacity_bytes"])
    requested=[s["id"] for s in targets]
    arrays=(visible,station,imager,radio,memory,cmds,energy)
    vectors=(x,y,sigma,guidance,rate_error,wheels)
    if n<10 or len(target_ids)!=n or any(a.shape!=(n,) for a in arrays):
        raise AssertionError("Mission03 physical recorder scalar shape mismatch")
    if any(a.shape!=(n,3) for a in vectors):
        raise AssertionError("Mission03 physical vector telemetry shape mismatch")
    if not np.all(np.isfinite(t)) or not np.all(np.diff(t)>0):
        raise AssertionError("Invalid monotonic time")
    dt=float(np.median(np.diff(t)))
    if not np.allclose(np.diff(t),dt,rtol=0,atol=1e-7):
        raise AssertionError("Non-uniform physical timestep")
    if not all(np.all(np.isfinite(a)) for a in (*arrays,*vectors)):
        raise AssertionError("Nonfinite physical telemetry")
    if not set(names).issubset(set(requested)):
        raise AssertionError("Unknown active target in physical samples")
    if not np.all(np.isin(cmds,[0,1])):
        raise AssertionError("Invalid camera command")
    if np.any(imager<0) or np.any(radio>0):
        raise AssertionError("Wrong bitstream direction")
    if np.any((imager>0)!=(cmds>0)):
        raise AssertionError("Real imager data disagree with capture command")
    if np.any((imager>0)&(~visible)):
        raise AssertionError("Capture outside target geometric visibility")
    if np.any((radio<0)&(~station)):
        raise AssertionError("Downlink outside ground-station access")
    if np.min(memory)<-1.0 or np.max(memory)>capacity+1.0:
        raise AssertionError("Physical storage capacity violated")
    if np.any(energy<-1e-6) or np.max(energy)>float(config.get(
        "battery_capacity_wh",float("inf")))+1e-5:
        raise AssertionError("Invalid battery energy in Wh")
    indices=np.flatnonzero(imager>0)
    if len(indices)!=len(requested):
        raise AssertionError(
            f"Expected {len(requested)} distinct real physical captures; found {len(indices)}"
        )
    observed=list(names[indices])
    if observed!=requested:
        raise AssertionError(f"Basilisk imager order mismatch: {observed} != {requested}")
    expected_bits=8*float(config["capture"]["product_bytes"])
    if not np.allclose(imager[indices]*dt,expected_bits,rtol=0,atol=1.0):
        raise AssertionError("Physical exposure product bytes inconsistent")
    angular=np.array([
        true_boresight_error_deg(s,p,g,boresight_B) for s,p,g in
        zip(sigma,x,y)],dtype=float)
    max_deg=math.degrees(4*math.atan(float(config["capture"]["maximum_attitude_mrp_error"])))
    for i in indices:
        if angular[i]>max_deg+0.001 or np.linalg.norm(guidance[i])>float(
            config["capture"]["maximum_attitude_mrp_error"])+1e-6:
            raise AssertionError(f"Actual body pointing error at t={t[i]:.1f}")
        if np.linalg.norm(rate_error[i])>float(
            config["capture"]["maximum_rate_error_rad_s"])+1e-6:
            raise AssertionError(f"Real body-rate tracking error at t={t[i]:.1f}")

    # Consistent with Basilisk's discrete memory bookkeeping.
    cumulative_generated=np.r_[0.0,np.cumsum(imager[1:]*np.diff(t))]
    cumulative_transmitted=np.r_[0.0,np.cumsum(-radio[1:]*np.diff(t))]
    generated=float(cumulative_generated[-1])
    transmitted=float(cumulative_transmitted[-1])
    stored=float(memory[-1])
    difference=generated-transmitted-stored
    bit_tolerance=max(1.0,2*dt*float(config["downlink"]["rate_bits_per_s"]))
    if abs(difference)>bit_tolerance:
        raise AssertionError(f"Physical bit conservation violated by {difference} bits")

    if not all(t[i]>0 for i in indices):
        raise AssertionError("Capture must occur after initial sample")
    switches=[e for e in events if e["event"]=="retarget_command"]
    if len(switches)!=len(requested)-1:
        raise AssertionError("Missing physical target switch commands")
    if not all(t[indices[k]]<switches[k]["t_s"]<t[indices[k+1]]
               for k in range(len(switches))):
        raise AssertionError("Retarget event not between physical captures")
    if any(float(np.linalg.norm(w))>=1e12 for w in wheels):
        raise AssertionError("Invalid reaction-wheel state")
    if any(v<float(power_reserve_wh)-1.0 for v in energy):
        raise AssertionError("Battery reserve violated by >1 Wh")

    # Runtime controller disables camera/radio on low reserve. This is not
    # equivalent to a continuous closed-loop electrical bus or sensor model.
    report={
        "model":"ONE Basilisk simulation: orbit + RW + real target switches + instrument/storage/downlink + solar/battery",
        "capture_count":len(indices),
        "targets":requested,
        "captures":[{
            "id":str(names[i]),
            "time_s":float(t[i]),
            "actual_boresight_error_deg":float(angular[i]),
            "physical_reaction_wheel_rpm":[float(v) for v in wheels[i]],
            "battery_wh":float(energy[i]),
            "generated_bits":expected_bits,
        } for i in indices],
        "retarget_events":switches,
        "generated_bits":generated,
        "transmitted_bits":transmitted,
        "remaining_stored_bits":stored,
        "capacity_bits":capacity,
        "balance_error_bits":difference,
        "balance_tolerance_bits":bit_tolerance,
        "fully_downlinked":bool(transmitted>=generated-bit_tolerance),
        "battery_min_wh":float(np.min(energy)),
        "battery_final_wh":float(energy[-1]),
        "battery_reserve_wh":float(power_reserve_wh),
        "max_wheel_speed_rpm":float(np.max(np.abs(wheels))),
        "physical_target_switch_count":len(switches),
        "stage_count":len(requested),
        "checks_passed":True,
        "limitations":[
            "Synthetic fixed-time-step byte products; not an optical camera with real pixels",
            "Power reserve gate checked at command intervals rather than continuously",
            "Basilisk panel and battery integrate energy; camera/radio electrical load is conservative always-on",
            "Ideal navigation with no sensor noise, saturation only where configured",
            "Rotating spherical Earth and no real UTC reference",
            "Geometric fixed-rate downlink consumes onboard data; no RF receiver or acknowledgment",
            "Mission03 is a fixed sequential demonstrator, NOT the Mission02 optimization scheduler",
        ],
    }
    output.mkdir(parents=True,exist_ok=True)
    (output/"mission03_summary.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    (output/"mission03_events.json").write_text(
        json.dumps(events,ensure_ascii=False,indent=2),encoding="utf-8")
    with (output/"mission03_states.csv").open("w",newline="",encoding="utf-8") as f:
        writer=csv.writer(f)
        writer.writerow(["time_s","physical_target_id","physical_boresight_error_deg",
                         "target_access","station_access","camera_command",
                         "imaging_bits_s","radio_bits_s","memory_bits","battery_wh",
                         "wheel1_rpm","wheel2_rpm","wheel3_rpm"])
        for i in range(n):
            writer.writerow([float(t[i]),str(names[i]),float(angular[i]),int(visible[i]),
                             int(station[i]),int(cmds[i]),float(imager[i]),
                             float(radio[i]),float(memory[i]),float(energy[i]),
                             *[float(v) for v in wheels[i]]])
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(10,4))
    ax.plot(t/60,memory/8e6,label="Onboard data (MB)")
    ax.plot(t/60,cumulative_transmitted/8e6,label="Transmitted (MB)")
    for j,i in enumerate(indices):
        ax.axvline(t[i]/60,ls="--",alpha=.5,label=f"Capture {requested[j]}")
    ax.set(xlabel="Synthetic elapsed time (min)",ylabel="MB",
           title="Mission03: physical retargeting, data storage and downlink")
    ax.grid(alpha=.2);ax.legend();fig.tight_layout()
    fig.savefig(output/"mission03_dataflow.png",dpi=160);plt.close(fig)
    return report
