"""Named controller action sequences. Add more here (e.g. buy-car) later."""
import config


def farm_sequence(drive_seconds=None):
    """One farm lap, mirroring the manual loop: drive ~40s, then X -> A -> A to restart.

    X = restart, A = confirm restart, A = start event. Throttle is held the whole
    drive phase (like taping down RT). Add steer steps here if your course needs it.
    """
    drive = config.DRIVE_SECONDS if drive_seconds is None else drive_seconds
    tap = config.TAP_HOLD
    return [
        {"throttle": 1.0, "duration": drive},   # RT held = always forward
        {"buttons": ["x"], "duration": tap},    # X: restart
        {"duration": config.MENU_DELAY},
        {"buttons": ["a"], "duration": tap},    # A: confirm restart
        {"duration": config.MENU_DELAY},
        {"buttons": ["a"], "duration": tap},    # A: start event
        {"duration": config.LOAD_DELAY},        # wait for reload, then loop
    ]


# TODO (later): buy_car_sequence(), spend_points_sequence().
# These navigate menus, so they need on-screen state detection to be reliable.
