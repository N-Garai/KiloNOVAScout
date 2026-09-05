from strands import Agent, tool
import json

@tool
def generate_indi_ascom_scripts(optimized_targets_json: str, exposure_time: int = 120, filter_name: str = "r") -> dict:
    """Generates execution scripts for ASCOM Alpaca and INDI robotic telescope control systems."""
    from ..tools.hardware_tools import generate_indi_xml, generate_ascom_json
    
    targets = json.loads(optimized_targets_json)
    
    indi_xml = generate_indi_xml(targets, exposure_time, filter_name)
    ascom_json = generate_ascom_json(targets, exposure_time, filter_name)
    
    return {
        "indi_xml": indi_xml,
        "ascom_json": ascom_json
    }

scheduler_agent = Agent(
    name="RoboticSchedulerAgent",
    system_prompt="You are a robotic observatory software engineer compiling hardware slew scripts.",
    tools=[generate_indi_ascom_scripts]
)