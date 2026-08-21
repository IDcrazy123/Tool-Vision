import unittest

from klippy.extras.tool_vision_toolchanger import (
    ToolchangerAdapter,
    ToolchangerError,
)


class Reactor:
    @staticmethod
    def monotonic():
        return 1.0


class Gcode:
    def __init__(self, toolchanger=None):
        self.commands = []
        self.toolchanger = toolchanger

    def run_script_from_command(self, command):
        self.commands.append(command)
        if self.toolchanger is not None and command.startswith("T"):
            self.toolchanger.status["tool_number"] = int(command[1:])


class CurrentToolchanger:
    def __init__(self):
        self.status = {"tool_number": 0, "tool_numbers": [0, 1, 2]}

    def get_status(self, eventtime):
        return dict(self.status)

    def lookup_tool(self, number):
        return type("Tool", (), {"get_offset": lambda self: [0.2, -0.1, 0.05]})()


class ToolchangerAdapterTests(unittest.TestCase):
    def test_current_status_api_is_supported(self):
        toolchanger = CurrentToolchanger()
        gcode = Gcode(toolchanger)
        adapter = ToolchangerAdapter(toolchanger, gcode, Reactor())
        self.assertEqual(adapter.tool_numbers(), [0, 1, 2])
        adapter.select(2)
        self.assertEqual(adapter.active_tool_number(), 2)
        self.assertEqual(gcode.commands, ["T2"])
        self.assertEqual(adapter.configured_offset(2), [0.2, -0.1, 0.05])

    def test_legacy_active_tool_object_is_supported(self):
        active = type("Tool", (), {"tool_number": 3})()
        changer = type("Legacy", (), {"active_tool": active, "tool_numbers": [3]})()
        adapter = ToolchangerAdapter(changer, Gcode(), Reactor())
        self.assertEqual(adapter.active_tool_number(), 3)
        self.assertEqual(adapter.tool_numbers(), [3])

    def test_empty_tool_list_is_rejected(self):
        changer = type("Empty", (), {"tool_numbers": []})()
        with self.assertRaises(ToolchangerError):
            ToolchangerAdapter(changer, Gcode(), Reactor()).tool_numbers()


if __name__ == "__main__":
    unittest.main()
