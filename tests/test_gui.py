from holoquiz.config import BotConfig
from holoquiz.gui import ControlPanelController
from holoquiz.runtime import FIND_ANSWER_FUNCTION, RuntimeControls


def test_control_panel_controller_updates_runtime_controls():
    controls = RuntimeControls.from_config(BotConfig(dry_run=True))
    controller = ControlPanelController(controls)

    controller.set_program_enabled(False)
    controller.set_dry_run(False)
    controller.set_function_enabled(FIND_ANSWER_FUNCTION, False)
    result = controller.set_send_delay_range("1", "3")

    assert result.ok is True
    assert controls.snapshot().program_enabled is False
    assert controls.get_config().dry_run is False
    assert controls.is_function_enabled(FIND_ANSWER_FUNCTION) is False
    assert controls.get_config().send_delay_min_seconds == 1.0
    assert controls.get_config().send_delay_max_seconds == 3.0


def test_control_panel_controller_rejects_invalid_send_delay():
    controls = RuntimeControls.from_config(BotConfig(send_delay_seconds=0.8))
    controller = ControlPanelController(controls)

    result = controller.set_send_delay_range("-1", "3")

    assert result.ok is False
    assert "0 or greater" in result.message
    assert controls.get_config().send_delay_seconds == 0.8


def test_control_panel_controller_rejects_non_numeric_send_delay():
    controls = RuntimeControls.from_config(BotConfig(send_delay_seconds=0.8))
    controller = ControlPanelController(controls)

    result = controller.set_send_delay_range("slow", "3")

    assert result.ok is False
    assert "number" in result.message
    assert controls.get_config().send_delay_seconds == 0.8


def test_control_panel_controller_rejects_reversed_send_delay_range():
    controls = RuntimeControls.from_config(BotConfig(send_delay_seconds=0.8))
    controller = ControlPanelController(controls)

    result = controller.set_send_delay_range("3", "1")

    assert result.ok is False
    assert "less than or equal" in result.message
    assert controls.get_config().send_delay_seconds == 0.8
