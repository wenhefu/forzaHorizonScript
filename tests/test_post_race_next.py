from types import SimpleNamespace
import unittest

from buy_car_detector import (
    BuyCarDetection,
    BuyCarScreenDetector,
    STATE_BUY_SELL_SHOWROOM_READY,
    STATE_PAUSE_MENU,
    STATE_POST_RACE_NEXT,
    STATE_UNKNOWN,
)


def ocr_item(text, x=0.5, y=0.5):
    return SimpleNamespace(text=text, ncx=x, ncy=y)


class PostRaceNextDetectionTests(unittest.TestCase):
    def test_next_stop_carousel_is_not_pause_menu(self):
        detector = BuyCarScreenDetector()
        detection = BuyCarDetection(STATE_UNKNOWN, 0.0, {})
        refined = detector.refine_with_ocr(
            detection,
            [
                ocr_item("下一站", 0.07, 0.11),
                ocr_item("腕带赛事", 0.15, 0.17),
                ocr_item("HORIZON", 0.22, 0.81),
                ocr_item("FESTIVAL", 0.22, 0.83),
                ocr_item("霜山一日游", 0.32, 0.67),
                ocr_item("街头竞速赛", 0.55, 0.67),
                ocr_item("A选择", 0.06, 0.93),
                ocr_item("返回", 0.12, 0.93),
            ],
        )

        self.assertEqual(STATE_POST_RACE_NEXT, refined.state)

    def test_real_pause_hub_stays_pause_menu_even_with_next_stop_tile(self):
        detector = BuyCarScreenDetector()
        detection = BuyCarDetection(STATE_UNKNOWN, 0.0, {})
        refined = detector.refine_with_ocr(
            detection,
            [
                ocr_item("剧情", 0.25, 0.12),
                ocr_item("车辆", 0.35, 0.12),
                ocr_item("我的地平线", 0.48, 0.12),
                ocr_item("创意中心", 0.68, 0.12),
                ocr_item("世界地图", 0.32, 0.28),
                ocr_item("下一站", 0.32, 0.62),
                ocr_item("设置", 0.60, 0.62),
            ],
        )

        self.assertEqual(STATE_PAUSE_MENU, refined.state)

    def test_buy_sell_showroom_is_not_pause_menu(self):
        detector = BuyCarScreenDetector()
        detection = BuyCarDetection(STATE_UNKNOWN, 0.0, {})
        refined = detector.refine_with_ocr(
            detection,
            [
                ocr_item("购买与出售", 0.15, 0.23),
                ocr_item("购买与出售", 0.27, 0.25),
                ocr_item("剧情", 0.21, 0.25),
                ocr_item("车辆", 0.33, 0.25),
                ocr_item("角色", 0.36, 0.25),
                ocr_item("车展", 0.07, 0.62),
                ocr_item("拍卖场", 0.07, 0.67),
                ocr_item("车辆通行证", 0.09, 0.72),
                ocr_item("票券车辆", 0.08, 0.82),
            ],
        )

        self.assertEqual(STATE_BUY_SELL_SHOWROOM_READY, refined.state)


if __name__ == "__main__":
    unittest.main()
