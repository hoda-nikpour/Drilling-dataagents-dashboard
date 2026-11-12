"""Run an isolated suite with fresh evidence; preserve earlier audit reports."""
import argparse
import importlib
from pathlib import Path
import sys


def main():
    cases={
        'workflow':('check_core_ui_workflow','core_ui_workflow_fixture.py'),
        'paging':('check_time_window_navigation','core_ui_workflow_fixture.py'),
        'navigation':('check_agent_interval_navigation','agent_interval_navigation_fixture.py'),
        'ordering':('check_interval_click_order','agent_interval_navigation_fixture.py'),
        'times':('check_core_ui_times',None),
        'resize':('check_plot_container_resize',None),
        'points':('check_agent_point_visibility',None),
    }
    parser=argparse.ArgumentParser();parser.add_argument('suite',choices=cases)
    suite=parser.parse_args().suite
    module_name,fixture=cases[suite];module=importlib.import_module(module_name)
    driver=module.static_driver if suite=='points' else getattr(module,'driver',module)
    driver.OUT=Path(__file__).resolve().parents[1]/'docs/pre_delivery_check_2026-11-12'/suite
    if fixture:driver.FIXTURE=driver.ROOT/'tools'/fixture
    if suite=='workflow':driver.PHYSICAL_SAVE=True
    driver.exercise=module.synthetic if suite=='points' else module.exercise
    sys.argv=[sys.argv[0]];driver.main()


if __name__=='__main__':main()
