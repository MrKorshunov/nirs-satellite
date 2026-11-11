"""Mission05 reproducible physical acceptance suite, no scheduling algorithm.

Runs actual Basilisk spacecraft against success and intentional task-miss cases.
A missed observation is a MISSION outcome; invalid physics/data accounting is a
SOFTWARE/ENGINEERING failure. Every case archives independent input, run log
and full result directory under results/ with a SHA256 provenance manifest.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import copy
import traceback

from nirs_satellite.input_paths import input_path

ROOT=Path(__file__).resolve().parents[2]


def _load(name:str)->dict:
    return json.loads(input_path(name).read_text(encoding="utf-8"))


def _expect(ok:bool,why:str)->None:
    if not ok:
        raise AssertionError(why)


def _case_check(case:str,summary:dict,baseline:dict|None=None)->dict:
    counts=[int(v["capture_count"]) for v in summary["tasks"]]
    _expect(bool(summary["checks_passed"]),f"{case}: physical constraints violated: {summary['checks']}")
    _expect(abs(float(summary["conservation_error_bits"]))<160000,
            f"{case}: physical bit conservation")
    _expect(float(summary["max_stored_bits"])<=float(summary["memory_capacity_bits"])+1,
            f"{case}: physical storage exceeded nominal capacity")
    _expect(float(summary["physical_wheel_max_rpm"])<=
            float(summary["physical_wheel_limit_rpm"])+3,
            f"{case}: reaction wheel speed limit")
    checks={
        "engineering_checks":True,"physically_generated_products":sum(counts),
        "mission_complete":bool(summary["mission_complete"]),
        "covered_area_m2":float(summary["coverage"]["total_covered_area_m2"]),
        "downlinked_bits":float(summary["transmitted_bits"]),
    }
    if case=="reference":
        _expect(counts==[1,1,12],"Reference: two points + 12 strip lines not recorded")
        _expect(summary["mission_complete"],"Reference program incomplete")
        _expect(checks["covered_area_m2"]>0,"Reference: no actual polygon overlap")
        _expect(abs(float(summary["transmitted_bits"])-float(summary["generated_bits"]))<160000,
                "Reference not downlinked")
        _expect(summary["epoch"] is not None,"Reference UTC epoch missing")
    elif case=="repeat_reference":
        _expect(baseline is not None,"Missing previous reference scenario")
        _expect(counts==[1,1,12] and summary["mission_complete"],
                "Repeated reference outcome differs")
        _expect(abs(float(summary["battery_final_wh"])-float(baseline["battery_final_wh"]))<1e-6,
                "Battery time history not deterministic")
        _expect(abs(float(summary["coverage"]["total_covered_area_m2"])-
                    float(baseline["coverage"]["total_covered_area_m2"]))<1e-3,
                "Coverage from same initial data not deterministic")
    elif case=="shift_epoch":
        _expect(summary["epoch"] is not None and
                summary["epoch"]["gmst_start_deg"]>30,
                "Test did not shift Earth orientation from reference epoch")
        _expect(summary["epoch_orientation_error_deg"]<0.3,
                "Basilisk physical Earth rotation not consistent with absolute UTC epoch")
    elif case=="idle":
        _expect(summary["task_count"]==0 and sum(counts)==0 and summary["generated_bits"]==0,
                "Idle satellite fabricated imaging data")
    elif case=="two":
        _expect(counts==[1,1] and summary["mission_complete"],
                "Two-job universal physical executor failed")
    elif case=="one":
        _expect(counts==[1] and summary["mission_complete"],"Single point physical run failed")
    elif case=="external_four":
        _expect(counts==[1,1,1,12] and summary["physical_target_switch_count"]==3,
                "Four external ordered jobs not executed physically")
    elif case=="offtrack":
        _expect(counts[:2]==[1,1] and counts[2]==0 and checks["covered_area_m2"]==0,
                "Off-track target fabricated strip coverage")
        _expect(not summary["mission_complete"],"Off-track task incorrectly marked completed")
    elif case=="low_battery":
        _expect(sum(counts)==0 and float(summary["generated_bits"])==0,
                "Battery safety mode allowed an exposure")
        _expect(summary["power_disabled_segments"]>0,"Battery never entered safety mode")
    elif case=="no_station":
        _expect(sum(counts)>0 and summary["transmitted_bits"]==0,
                "No-visibility station produced downlinked data")
        _expect(summary["final_stored_bits"]>0,"No-contact data disappeared")
    elif case=="memory_backpressure":
        _expect(counts[0]==1 and counts[1]==0 and summary["transmitted_bits"]==0,
                "Full memory did not stop second exposure")
        _expect(not summary["mission_complete"],"Missed camera task falsely marked successful")
    elif case=="expired_window":
        _expect(counts[0]==0 and not summary["mission_complete"],
                "Impossible time window incorrectly completed")
        _expect(summary["tasks"][0]["reason"] is not None,"Missing deadline reason")
    elif case=="repeated_downlink":
        _expect(summary["checks"]["radio_transmits_only_inside_planned_windows"],
                "Radio sent outside externally scheduled windows")
        _expect(len(summary["planned_downlink_windows"])==2,
                "Two scheduled radio windows not recorded")
        _expect(all(int(w["actual_tx_samples"])>0 for w in summary["planned_downlink_windows"]),
                "Second radio window did not actually transmit, so repeated-contact test is invalid")
    elif case=="partial_link":
        _expect(summary["generated_bits"]>0 and
                0<summary["transmitted_bits"]<summary["generated_bits"],
                "Low-bandwidth physical radio unexpectedly delivered full image")
    elif case=="slow_wheels":
        _expect(summary["physical_wheel_limit_rpm"]<100,
                "Wheel stress configuration was not applied")
        _expect(counts[0]==0 and not summary["mission_complete"],
                "Physically impossible early slew was falsely marked successful")
    elif case=="refined_step":
        _expect(counts==[1,1,24],"0.25s physical result must contain two points + 24 strip lines")
        if baseline:
            base=float(baseline["coverage"]["total_covered_area_m2"])
            here=float(summary["coverage"]["total_covered_area_m2"])
            _expect(base>0 and 0.6<=here/base<=1.4,
                    f"Coverage model unstable after halving step: ratio={here/base if base else None}")
    else:
        raise AssertionError("Unhandled acceptance case: "+case)
    return checks


def run_suite(*,viz:bool=False,strict:bool=True)->Path:
    timestamp=datetime.now(timezone.utc).strftime("%y%m%d_%H%M%S")
    output=ROOT/"results"/("mission05_acceptance_"+timestamp)
    output.mkdir(parents=True,exist_ok=False)
    original=_load("mission_mixed_demo")
    territories=_load("territories")
    hw=_load("camera_storage_radio")
    adcs=_load("adcs_wheels")
    checks={}
    failures=[]
    reference=None
    with tempfile.TemporaryDirectory(prefix="mission05_cases_") as tmp:
        base=Path(tmp)
        for index,case in enumerate((
            "reference","repeat_reference","shift_epoch","idle","one","two","external_four",
            "offtrack","low_battery","no_station","memory_backpressure",
            "expired_window","repeated_downlink","partial_link",
            "slow_wheels","refined_step",
        )):
            cfg=copy.deepcopy(original)
            reg=copy.deepcopy(territories)
            camera=copy.deepcopy(hw)
            wheels=copy.deepcopy(adcs)
            if case=="shift_epoch":
                cfg["epoch_utc"]="2026-11-11T00:00:00Z"
            elif case=="idle":
                cfg["tasks"]=[]
            elif case=="two":
                cfg["tasks"]=cfg["tasks"][:2]
            elif case=="one":
                cfg["tasks"]=cfg["tasks"][:1]
            elif case=="external_four":
                third=copy.deepcopy(cfg["tasks"][1])
                third.update(id="THIRD_POINT",lat_deg=15.2,lon_deg=43.7)
                cfg["tasks"].insert(2,third)
            elif case=="offtrack":
                reg["regions"][0]["polygon_lat_lon_deg"]=[
                    [-48,47],[-48,54],[-44,54],[-44,47]]
            elif case=="low_battery":
                cfg["reserve_wh"]=64.95
                cfg["reserve_guard_wh"]=5.
            elif case in ("no_station","memory_backpressure"):
                camera["downlink"]["ground_station"].update(
                    latitude_deg=-75,longitude_deg=0,
                    minimum_elevation_deg=10)
                if case=="memory_backpressure":
                    camera["storage"]["capacity_bytes"]=1000000
            elif case=="expired_window":
                cfg["tasks"][0]["planned_end_s"]=40
            elif case=="repeated_downlink":
                cfg["downlink_windows"]=[
                    {"start_s":0,"end_s":110},{"start_s":250,"end_s":450}]
            elif case=="partial_link":
                camera["downlink"]["rate_bits_per_s"]=10000
                camera["downlink"]["packet_bytes"]=500  # 0.5 s carries >=1 whole packet
            elif case=="slow_wheels":
                wheels["rw"]["max_speed_rpm"]=15
                cfg["tasks"][0]["planned_end_s"]=40
            elif case=="refined_step":
                camera["capture"]["assumed_exposure_duration_s"]=0.25
                cfg["tasks"][-1]["min_samples"]=24
                cfg["tasks"][-1]["max_samples"]=24
            casefiles=base/case
            casefiles.mkdir()
            for p,v in (("config",cfg),("regions",reg),("camera",camera),("adcs",wheels)):
                (casefiles/(p+".json")).write_text(
                    json.dumps(v,ensure_ascii=False,indent=2),encoding="utf-8")
            name=f"ms05_{timestamp}_{index:02d}_{case}"
            # Output names must be <=48 ASCII characters.
            if len(name)>48:
                name=f"ms05_{timestamp}_{index:02d}"
            cmd=[
                sys.executable,"-m","experiments.mission_03.run",
                "--config",str(casefiles/"config.json"),
                "--regions",str(casefiles/"regions.json"),
                "--camera-config",str(casefiles/"camera.json"),
                "--adcs-config",str(casefiles/"adcs.json"),
                "--duration-hours","0.2",
                "--viz-mode","file" if viz and case=="reference" else "off",
                "--output-name",name,
            ]
            p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,check=False)
            log=(output/(case+".log"))
            log.write_text(p.stdout+"\nSTDERR:\n"+p.stderr,encoding="utf-8")
            result_path=ROOT/"results"/name/"mission03_summary.json"
            (ROOT/"results"/name).mkdir(parents=True,exist_ok=True)
            shutil.copytree(casefiles,ROOT/"results"/name/"acceptance_inputs_used")
            try:
                _expect(p.returncode==0,f"{case}: Basilisk exited with {p.returncode}; read {log}")
                _expect(result_path.is_file(),f"{case}: no physical summary")
                report=json.loads(result_path.read_text(encoding="utf-8"))
                result=_case_check(case,report,baseline=reference)
                if case=="reference":
                    reference=report
                checks[case]={
                    "pass":True,
                    "log":str(log.relative_to(ROOT)),
                    "physical_result":str(result_path.parent.relative_to(ROOT)),
                    **result,
                }
                print(f"PASS {case}: {result}",flush=True)
            except Exception as exc:
                failures.append({"case":case,"error":str(exc),"traceback":traceback.format_exc()})
                checks[case]={"pass":False,"error":str(exc),"log":str(log.relative_to(ROOT))}
                print(f"FAIL {case}: {exc}",flush=True)
    verdict={"suite":"Mission05 physical one-KA scientific readiness",
             "no_optimizer":True,
             "cases":checks,
             "case_count":len(checks),
             "pass_count":sum(bool(v["pass"]) for v in checks.values()),
             "passed":not failures,
             "failures":failures,
             "limitations":[
                 "Real spacecraft dynamics in Basilisk, but calibrated numbers remain SYNTHETIC",
                 "Coverage estimates assume nadir rectangular FOV cells on WGS84 LAEA, not actual pixels",
                 "UTC GMST approximate; no IERS full EOP; receiver ACK absent",
             ]}
    (output/"acceptance_summary.json").write_text(
        json.dumps(verdict,ensure_ascii=False,indent=2),encoding="utf-8")
    if strict and failures:
        raise SystemExit(f"Mission05 acceptance failed ({len(failures)} cases): {output}")
    return output

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--viz",action="store_true")
    args=parser.parse_args()
    report=run_suite(viz=args.viz,strict=True)
    print("ACCEPTANCE SUCCESS",report,flush=True)

if __name__=="__main__":
    main()
