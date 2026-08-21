"""Compatibility adapter for old and current klipper-toolchanger APIs."""


class ToolchangerError(RuntimeError):
    """Toolchanger state is incomplete or incompatible."""


class ToolchangerAdapter:
    def __init__(self, toolchanger, gcode, reactor, select_template="T{tool}"):
        self.toolchanger = toolchanger
        self.gcode = gcode
        self.reactor = reactor
        self.select_template = select_template

    def status(self):
        try:
            value = self.toolchanger.get_status(self.reactor.monotonic())
            return value if isinstance(value, dict) else {}
        except (AttributeError, TypeError):
            return {}

    def tool_numbers(self):
        values = getattr(self.toolchanger, "tool_numbers", None)
        if values is None:
            values = self.status().get("tool_numbers")
        if values is None and hasattr(self.toolchanger, "tools"):
            values = self.toolchanger.tools.keys()
        try:
            numbers = sorted(set(int(value) for value in values))
        except (TypeError, ValueError):
            raise ToolchangerError("toolchanger returned invalid tool numbers")
        if not numbers:
            raise ToolchangerError("toolchanger has no assigned tools")
        return numbers

    def active_tool_number(self):
        active = getattr(self.toolchanger, "active_tool", None)
        if active is not None and hasattr(active, "tool_number"):
            return int(active.tool_number)
        value = self.status().get("tool_number", -1)
        try:
            value = int(value)
        except (TypeError, ValueError):
            return None
        return value if value >= 0 else None

    def select(self, number):
        number = int(number)
        if number not in self.tool_numbers():
            raise ToolchangerError("tool T%d is not assigned" % number)
        if self.active_tool_number() != number:
            self.gcode.run_script_from_command(
                self.select_template.format(tool=number)
            )
        if self.active_tool_number() != number:
            raise ToolchangerError("toolchanger did not activate T%d" % number)

    def configured_offset(self, number):
        """Best available current offset, used only to approach a fixture."""
        tool = None
        if hasattr(self.toolchanger, "lookup_tool"):
            try:
                tool = self.toolchanger.lookup_tool(int(number))
            except Exception:
                tool = None
        if tool is None and hasattr(self.toolchanger, "tools"):
            tool = self.toolchanger.tools.get(int(number))
        if tool is None:
            return [0.0, 0.0, 0.0]
        if hasattr(tool, "get_offset"):
            try:
                values = tool.get_offset()
                return [float(values[index]) for index in range(3)]
            except (TypeError, ValueError, IndexError):
                pass
        return [
            float(getattr(tool, "gcode_x_offset", 0.0) or 0.0),
            float(getattr(tool, "gcode_y_offset", 0.0) or 0.0),
            float(getattr(tool, "gcode_z_offset", 0.0) or 0.0),
        ]
