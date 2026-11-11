"""Auditable physical telemetry for any fixed-order point/strip program.

All observation records originate from Basilisk DataNodeUsage. Each synthetic
strip line is attributed to actual spacecraft attitude and orbit geometry.
Area is local projected approximation, NOT terrain- or polygon-clipped pixels.
"""
from __future__ import annotations
import csv,json,math
import numpy as np
from pathlib import Path
from Basilisk.utilities import macros
from experiments.adcs_01.kinematics import true_boresight_error_deg
from experiments.power_01.analysis import analyse_run as analyse_power

def _task_at_sample(t:float,events:list,first:str)->str:
    result=first
    for event in events:
        if event["event"]=="task_assigned" and t>float(event["t_s"])+1e-8:
            result=event["task"]
    return result

def save_results(*,out:Path,cfg:dict,regions:dict,source_hashes:dict,
                 state,target_rec,target_access,adcs,data,power,director,
                 bin_path,step:float):
    t=np.asarray(data.instrument_data_rec.times(),dtype=float)*1e-9
    position=np.asarray(state.r_BN_N,dtype=float)
    sigma=np.asarray(state.sigma_BN,dtype=float)
    targets=np.asarray(target_rec.r_LN_N,dtype=float)
    access=np.asarray(target_access.hasAccess,dtype=bool)
    station=np.asarray(data.station_access_rec.hasAccess,dtype=bool)
    gen=np.asarray(data.instrument_data_rec.baudRate,dtype=float)
    tx=np.asarray(data.transmitter_rec.baudRate,dtype=float)
    storage=np.asarray(data.storage_rec.storageLevel,dtype=float)
    battery=np.asarray(power.battery_rec.storageLevel,dtype=float)/3600.
    panel=np.asarray(power.panel_rec.netPower,dtype=float)
    wheels=np.asarray(adcs.rw_recorder.wheelSpeeds,dtype=float)[:,:3]/macros.RPM
    n=len(t)
    vectors=(position,sigma,targets,wheels)
    scalars=(access,station,gen,tx,storage,battery,panel)
    if n<3 or any(v.shape!=(n,3) for v in vectors) or any(s.shape!=(n,) for s in scalars):
        raise AssertionError("Unsynchronized physical spacecraft data")
    if not all(np.all(np.isfinite(v)) for v in (t,*vectors,*scalars)):
        raise AssertionError("Nonfinite Basilisk telemetry")
    if not np.allclose(np.diff(t),step,rtol=0,atol=1e-8):
        raise AssertionError("Physical samples have inconsistent time step")
    for rec in (state,target_rec,target_access,data.station_access_rec,
                data.instrument_data_rec,data.transmitter_rec,data.storage_rec,
                power.battery_rec,power.panel_rec,adcs.rw_recorder):
        if not np.allclose(np.asarray(rec.times())*1e-9,t,rtol=0,atol=1e-8):
            raise AssertionError("Physical recorders are not synchronous")
    bore=np.asarray([true_boresight_error_deg(s,p,q,adcs.config["instrument_boresight_B"])
                     for s,p,q in zip(sigma,position,targets)])
    ids=np.asarray([_task_at_sample(float(v),director.events,cfg["tasks"][0]["id"])
                    for v in t],dtype=str)
    captures=np.flatnonzero(gen>1e-6)
    at_shot=bore[captures]
    maximum=math.degrees(4*math.atan(float(data.config["capture"]["maximum_attitude_mrp_error"])))
    expected_bits=0.0
    details=[]
    for job in cfg["tasks"]:
        name=job["id"];kind=job.get("kind","point")
        count=director.capture_count[name]
        size=(int(job["sample_bytes"]) if kind=="strip" else
              int(job.get("product_bytes",data.config["capture"]["product_bytes"])))
        expected_bits+=count*size*8
        details.append({
            "id":name,"kind":kind,"capture_count":count,
            "status":director.task_status[name],
            "capture_times_s":director.capture_times[name],
            "generated_bits":count*size*8,
            "region_id":job.get("region_id"),
            "required_samples":int(job.get("min_samples",1)),
            "approx_observed_length_m":sum(x["along_track_m"] for x in director.lines if x["task"]==name),
            "approx_swath_sample_area_m2":sum(x["approx_area_m2"] for x in director.lines if x["task"]==name),
        })
    bits_in=float(np.sum(gen[1:]*np.diff(t)))
    bits_out=float(np.sum(-tx[1:]*np.diff(t)))
    remain=float(storage[-1])
    tolerance=max(1.,2*step*float(data.config["downlink"]["rate_bits_per_s"]))
    max_wheel=float(np.max(np.abs(wheels)))
    limit=float(adcs.config["rw"]["max_speed_rpm"])
    limit_storage=8*float(data.config["storage"]["capacity_bytes"])
    checks={
        "physical_generated_bytes_match_event_log":abs(expected_bits-bits_in)<1.0,
        "actual_boresight_for_every_line":bool(np.all(at_shot<=maximum+0.15)),
        "only_visible_ground_targets_imaged":bool(np.all(access[captures])),
        "actual_downlink_has_ground_contact":bool(np.all(station[tx<-1e-7])),
        "wheel_speed_within_limit":max_wheel<=limit+3.,
        "storage_within_capacity":bool(np.min(storage)>=-1 and np.max(storage)<=limit_storage+1),
        "data_conservation":abs(bits_in-bits_out-remain)<=tolerance,
        "battery_within_capacity":bool(np.min(battery)>=-1e-3 and
             np.max(battery)<=float(power.config["battery_capacity_wh"])+1e-3),
        "battery_reserve_not_violated":bool(np.min(battery)>=float(cfg["reserve_wh"])-1e-3),
        "nonnegative_image_rate_and_negative_tx":bool(np.all(gen>=-1e-8) and np.all(tx<=1e-8)),
        "all_tasks_completed":all(x["status"]=="completed" for x in details),
    }
    output=out
    output.mkdir(parents=True,exist_ok=True)
    with (output/"mission03_states.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f)
        w.writerow(["time_s","task_id","target_access","station_access",
                    "actual_boresight_error_deg","generated_rate_bps",
                    "downlink_rate_bps","stored_bits","battery_wh",
                    "panel_w","rw1_rpm","rw2_rpm","rw3_rpm"])
        for i in range(n):
            w.writerow([float(t[i]),str(ids[i]),int(access[i]),int(station[i]),
                        float(bore[i]),float(gen[i]),float(tx[i]),float(storage[i]),
                        float(battery[i]),float(panel[i]),*map(float,wheels[i])])
    with (output/"mission03_strip_footprints.csv").open("w",newline="",encoding="utf-8") as f:
        columns=["t_s","task","lat_deg","lon_deg","altitude_m",
                 "region_signed_distance_m","swath_width_m","along_track_m",
                 "approx_area_m2","data_bits"]
        writer=csv.DictWriter(f,fieldnames=columns)
        writer.writeheader()
        writer.writerows(director.lines)
    with (output/"mission03_groundtrack.csv").open("w",newline="",encoding="utf-8") as f:
        columns=["t_s","lat_deg","lon_deg","altitude_m","task"]
        w=csv.DictWriter(f,fieldnames=columns)
        w.writeheader()
        w.writerows(director.ground_track)
    (output/"mission03_events.json").write_text(
        json.dumps(director.events,ensure_ascii=False,indent=2),encoding="utf-8")
    power_report=analyse_power(times=t,components=power,output=output)
    power_report["limitations"]=[
        "Synthetic fixed Sun direction, body-fixed panel and discrete power mode commands",
        "Maneuver-wheel electrical power not hardware-calibrated",
        "Battery reserve is monitored, not a guarantee of never crossing threshold",
    ]
    (output/"power_summary.json").write_text(
        json.dumps(power_report,ensure_ascii=False,indent=2),encoding="utf-8")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(3,1,figsize=(11,8),sharex=True)
    axes[0].plot(t/60,bore,label="Real pointing error (degrees)")
    axes[1].plot(t/60,storage/8e6,label="Onboard memory (MB)")
    axes[2].plot(t/60,battery,label="Basilisk battery (Wh)")
    for e in director.events:
        if e["event"]=="task_assigned" and e["t_s"]>0:
            for ax in axes: ax.axvline(e["t_s"]/60,color="tab:orange",alpha=.3,linestyle="--")
    for ax in axes:
        ax.grid(alpha=.2);ax.legend()
    axes[2].set_xlabel("Model time (minutes)")
    fig.suptitle("Mission03 universal point + along-track strip executor")
    fig.tight_layout();fig.savefig(output/"mission03_dataflow.png",dpi=150);plt.close(fig)
    result={
        "model":"One continuous Basilisk physical mission with provided-order point/strip task execution",
        "provenance":"SYNTHETIC. No optimizer, no camera pixel images.",
        "tasks":details,
        "task_count":len(details),
        "completed_tasks":sum(v["status"]=="completed" for v in details),
        "physical_target_switch_count":len(director.switch_times),
        "sample_count":n,
        "step_s":float(step),
        "duration_s":float(t[-1]),
        "actual_capture_max_boresight_error_deg":float(np.max(at_shot)) if len(at_shot) else None,
        "physical_wheel_max_rpm":max_wheel,
        "physical_wheel_limit_rpm":limit,
        "generated_bits":bits_in,"transmitted_bits":bits_out,
        "final_stored_bits":remain,
        "max_stored_bits":float(np.max(storage)),
        "memory_capacity_bits":limit_storage,
        "conservation_error_bits":bits_in-bits_out-remain,
        "battery_initial_wh":float(battery[0]),
        "battery_final_wh":float(battery[-1]),
        "battery_minimum_wh":float(np.min(battery)),
        "battery_reserve_wh":float(cfg["reserve_wh"]),
        "power_enabled_segments":sum(director.power_enabled_segments),
        "power_disabled_segments":len(director.power_enabled_segments)-sum(director.power_enabled_segments),
        "strip_samples":len(director.lines),
        "approx_swath_sample_area_m2":sum(v["approx_area_m2"] for v in director.lines),
        "station_tx_samples":int(np.sum(tx<-1e-7)),
        "checks":checks,
        "checks_passed":all(checks.values()),
        "vizard_file":str(bin_path) if bin_path else None,
        "vizard_created":bool(bin_path and bin_path.is_file() and bin_path.stat().st_size>0),
        "sources_sha256":source_hashes,
        "limitations":[
            "Every strip sample is synthetic bytes generated by real Basilisk simpleInstrument, not an optical image",
            "Swath intersection uses sampled nadir ground track and approximate cross-track FOV around a spherical Earth",
            "No polygon-clipped pixel-level coverage or actual georeferencing precision; sample area is approximate",
            "Only an externally provided fixed-order program is executed; no optimization or automatic scheduling",
            "Physical pointing, wheel dynamics, storage, transmitter access and battery power states are integrated",
            "SimpleNav is ideal; link is fixed-rate and has no receiver ACK or bit-error model",
            "No WGS84 real epoch UTC, J2, orbit perturbations, terrain, cloud cover or detailed optics",
        ],
    }
    (output/"mission03_summary.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result
