"""Virtual Xbox 360 controller wrapper (vgamepad / ViGEmBus). Windows-only."""
import logging
import threading
import time

import vgamepad as vg

# Friendly names -> XInput button enums, so config.py can use plain strings.
BUTTONS = {
    "a": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
    "b": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
    "x": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
    "y": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
    "lb": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
    "rb": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
    "start": vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
    "back": vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
    "dpad_up": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
    "dpad_down": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
    "dpad_left": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
    "dpad_right": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
}


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


class Gamepad:
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger("forza6helper")
        self._lock = threading.Lock()
        self.logger.info("Creating vgamepad VX360Gamepad")
        try:
            self.pad = vg.VX360Gamepad()
        except Exception as e:  # most often: ViGEmBus driver not installed
            self.logger.exception("VX360Gamepad creation failed")
            raise RuntimeError("创建虚拟手柄失败，请确认已安装 ViGEmBus 驱动。原始错误：" + str(e))
        self.logger.info("VX360Gamepad created; waiting for Windows enumeration")
        time.sleep(1.0)  # let Windows enumerate the virtual device first
        self.neutral()
        self.logger.info("Virtual gamepad ready and neutral")

    def neutral(self):
        """Release all inputs (no throttle, no steering, no buttons)."""
        with self._lock:
            self.logger.debug("gamepad neutral")
            self.pad.reset()
            self.pad.update()

    def apply(self, throttle=0.0, brake=0.0, steer=0.0, buttons=()):
        """Set full control state in one shot. throttle/brake 0..1, steer -1..1."""
        with self._lock:
            self.logger.debug(
                "gamepad apply throttle=%.2f brake=%.2f steer=%.2f buttons=%s",
                throttle,
                brake,
                steer,
                list(buttons),
            )
            self.pad.reset()
            self.pad.right_trigger_float(value_float=_clamp(throttle, 0.0, 1.0))
            self.pad.left_trigger_float(value_float=_clamp(brake, 0.0, 1.0))
            self.pad.left_joystick_float(x_value_float=_clamp(steer, -1.0, 1.0),
                                         y_value_float=0.0)
            for name in buttons:
                if name not in BUTTONS:
                    raise ValueError(f"unknown button {name!r}; valid: {sorted(BUTTONS)}")
                self.pad.press_button(button=BUTTONS[name])
            self.pad.update()

    def tap(self, name, hold=0.1):
        """Press then release one button (for menu navigation later)."""
        if name not in BUTTONS:
            raise ValueError(f"unknown button {name!r}; valid: {sorted(BUTTONS)}")
        with self._lock:
            self.logger.debug("gamepad tap button=%s hold=%.2f", name, hold)
            self.pad.press_button(button=BUTTONS[name])
            self.pad.update()
            time.sleep(hold)
            self.pad.release_button(button=BUTTONS[name])
            self.pad.update()
