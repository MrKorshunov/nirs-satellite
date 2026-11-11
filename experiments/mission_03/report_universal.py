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
from experiments.mission_03.timeline import schedule_task_record,radio_window_open
from experiments.mission_03.epoch import date_at
from experiments.mission_03.coverage import polygon_coverage

def _task_at_sample(t:float,events:list,first:str)->str:
    result=first
    for event in events:
        if event["event"]=="task_assigned" and t>float(event["t_s"])+1e-8:
            result=event["task"]
    return result

def save_results(*,out:Path,cfg:dict,regions:dict,source_hashes:dict,
                 state,target_rec,target_access,adcs,data,power,director,
                 bin_path,step:float,epoch_info:dict|None=None):
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
    ids=np.asarray([_task_at_sample(float(v),director.events,
                                   cfg["tasks"][0]["id"] if cfg["tasks"] else "")
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
        planned=schedule_task_record(job,director.capture_times[name],
                                     director.task_status[name],
                                     director.task_reason[name])
        details.append({
            "id":name,"kind":kind,"capture_count":count,
            **planned,
            "blocker_samples":director.blocked[name],
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
    # Plan and actual transmission: fixed-order schedule does not choose
    # windows. Out-of-plan downlink is a physical-policy validation failure.
    planned_tx=np.asarray([radio_window_open(cfg,float(v)) for v in t],dtype=bool)
    downlink_outside=bool(np.any((tx<-1e-7)&(~planned_tx)))
    planned_radio=[]
    for win in cfg.get("downlink_windows",[{"start_s":0.0,"end_s":float(t[-1])+step}]):
        inside=(t>=float(win["start_s"]))&(t<float(win["end_s"]))
        sending=(tx<0)&inside
        planned_radio.append({
            "planned_start_s":float(win["start_s"]),
            "planned_end_s":float(win["end_s"]),
            "actual_first_tx_s":float(t[np.flatnonzero(sending)[0]]) if np.any(sending) else None,
            "actual_last_tx_s":float(t[np.flatnonzero(sending)[-1]]) if np.any(sending) else None,
            "actual_sent_bits":float(np.sum((-tx[1:])*np.diff(t)*(inside[1:]))),
            "actual_tx_samples":int(np.count_nonzero(sending)),
        })
    coverage=polygon_coverage(regions,cfg["tasks"],director.lines,director.ground_track,step)
    coverage_geojson=coverage.pop("coverage_geojson")
    (out/"mission05_footprints.geojson").write_text(
        json.dumps(coverage_geojson,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"mission05_coverage.json").write_text(
        json.dumps(coverage,ensure_ascii=False,indent=2),encoding="utf-8")
    for detail in details:
        if detail["kind"]=="strip":
            detail.update(coverage["task_coverage"].get(detail["id"],{}))
    # Physical 'samples generated' and mission objective 'area covered'
    # are distinct. Do not claim a region is covered just because N images
    # were acquired. Future optimizers can use the actual continuous KPI.
    for job,detail in zip(cfg["tasks"],details):
        goal=float(job.get("min_coverage_percent",0)) if detail["kind"]=="strip" else 0.
        measured=float(detail.get("covered_percent",0))
        detail["coverage_goal_percent"]=goal if detail["kind"]=="strip" else None
        detail["coverage_goal_met"]=measured+1e-8>=goal if detail["kind"]=="strip" else None
    mission_complete=all(
        v["status"]=="completed" and
        (v["coverage_goal_met"] is not False) for v in details)
    # Independently confirm the actual Basilisk Earth-fixed longitude at t=0
    # agrees with UTC+UT1-based GMST and inertial spacecraft longitude.
    # This checks the installed orientation rather than trusting a JSON label.
    orientation_error_deg=None
    if epoch_info is not None:
        inertial_lon0=math.degrees(math.atan2(position[0,1],position[0,0]))
        expected_lon=(inertial_lon0-float(epoch_info["gmst_start_deg"])+180.)%360.-180.
        observed_lon=float(director.ground_track[0]["lon_deg"])
        orientation_error_deg=abs((observed_lon-expected_lon+180.)%360.-180.)
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
        "radio_transmits_only_inside_planned_windows":not downlink_outside,
        "coverage_union_bounded_by_region_area":all(
            0<=q["covered_area_m2"]<=q["region_area_m2"]+1
            for q in coverage["regions"].values()),
        # Check AFTER the continuous native dynamics run, not inside a
        # SWIG UpdateState callback; false captures are physical failures.
        "all_actual_strip_lines_intersect_territory":all(
            float(line.get("instant_footprint_overlap_m2",0.0))>0.
            for line in director.lines),
        "geometry_callbacks_without_exceptions":not director.geometry_errors,
        "basilisk_earth_longitude_matches_utc_gmst":(
            orientation_error_deg is None or orientation_error_deg<0.3),
    }
    output=out
    output.mkdir(parents=True,exist_ok=True)
    with (output/"mission03_states.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f)
        w.writerow(["time_s","utc_iso8601","task_id","target_access","station_access",
                    "actual_boresight_error_deg","generated_rate_bps",
                    "downlink_rate_bps","stored_bits","battery_wh",
                    "panel_w","rw1_rpm","rw2_rpm","rw3_rpm"])
        for i in range(n):
            w.writerow([float(t[i]),date_at(epoch_info["epoch_utc"],t[i]) if epoch_info else "",
                        str(ids[i]),int(access[i]),int(station[i]),
                        float(bore[i]),float(gen[i]),float(tx[i]),float(storage[i]),
                        float(battery[i]),float(panel[i]),*map(float,wheels[i])])
    with (output/"mission03_strip_footprints.csv").open("w",newline="",encoding="utf-8") as f:
        columns=["t_s","utc_iso8601","task","lat_deg","lon_deg","altitude_m",
                 "region_signed_distance_m","swath_width_m","along_track_m",
                 "instant_footprint_overlap_m2","approx_area_m2","data_bits"]
        writer=csv.DictWriter(f,fieldnames=columns)
        writer.writeheader()
        for line in director.lines:
            writer.writerow({**line,"utc_iso8601":date_at(epoch_info["epoch_utc"],line["t_s"])
                             if epoch_info else ""})
    with (output/"mission03_groundtrack.csv").open("w",newline="",encoding="utf-8") as f:
        columns=["t_s","utc_iso8601","lat_deg","lon_deg","altitude_m","task"]
        w=csv.DictWriter(f,fieldnames=columns)
        w.writeheader()
        for item in director.ground_track:
            w.writerow({**item,"utc_iso8601":date_at(epoch_info["epoch_utc"],item["t_s"])
                        if epoch_info else ""})
    events_with_utc=[
        {**ev,"utc_iso8601":date_at(epoch_info["epoch_utc"],ev["t_s"])
         if epoch_info else None} for ev in director.events
    ]
    (output/"mission03_events.json").write_text(
        json.dumps(events_with_utc,ensure_ascii=False,indent=2),encoding="utf-8")
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
        "mission_complete":mission_complete,
        "mission_outcome":"complete" if mission_complete else "partially_completed_or_missed",
        "epoch":epoch_info,
        "epoch_orientation_error_deg":orientation_error_deg,
        "utc_end":date_at(epoch_info["epoch_utc"],t[-1]) if epoch_info else None,
        "planned_downlink_windows":planned_radio,
        "coverage":coverage,
        "geometry_errors":director.geometry_errors,
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
            "UTC epoch + approximate GMST and WGS84 ground footprint; not high-precision EOP/ITRF or real satellite ephemeris",
            "WGS84 equal-area geometric swath-union coverage, not actual optical pixels or verified image quality",
            "Two-body orbit, no J2/drag, terrain, clouds or detailed optical ray tracing",
        ],
    }
    (output/"mission03_summary.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result
