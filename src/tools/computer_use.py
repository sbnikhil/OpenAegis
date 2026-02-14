import base64
import io
from pathlib import Path
from typing import Any
import pyautogui
import mss
from PIL import Image
from src.core.config import Config
from src.core.logging_setup import get_logger

logger = get_logger(__name__)

class ComputerUseTools:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        pyautogui.PAUSE = self.config.COMPUTER_USE_ACTION_DELAY
        pyautogui.FAILSAFE = self.config.COMPUTER_USE_FAILSAFE
    
    def screenshot(self, region: tuple[int, int, int, int] | None = None, save_path: str | None = None) -> dict[str, Any]:
        logger.info("taking_screenshot", region=region, save_path=save_path)
        
        try:
            with mss.mss() as sct:
                if region:
                    x, y, width, height = region
                    monitor = {"top": y, "left": x, "width": width, "height": height}
                else:
                    monitor = sct.monitors[1]
                
                screenshot = sct.grab(monitor)
                img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
                
                if save_path:
                    img.save(save_path)
                    logger.info("screenshot_saved", path=save_path)
                    return {
                        "success": True,
                        "path": save_path,
                        "width": img.width,
                        "height": img.height,
                    }
                else:
                    buffer = io.BytesIO()
                    img.save(buffer, format="PNG")
                    img_bytes = buffer.getvalue()
                    img_base64 = base64.b64encode(img_bytes).decode("utf-8")
                    
                    logger.info("screenshot_captured", width=img.width, height=img.height)
                    return {
                        "success": True,
                        "image_base64": img_base64,
                        "width": img.width,
                        "height": img.height,
                    }
        
        except Exception as e:
            logger.error("screenshot_failed", error=str(e))
            raise
    
    def mouse_move(self, x: int, y: int, duration: float | None = None) -> dict[str, Any]:
        logger.info("mouse_move", x=x, y=y, duration=duration)
        
        try:
            duration = duration or self.config.COMPUTER_USE_MOUSE_MOVE_DURATION
            pyautogui.moveTo(x, y, duration=duration)
            
            logger.info("mouse_moved", x=x, y=y)
            return {
                "success": True,
                "action": "mouse_move",
                "x": x,
                "y": y,
            }
        
        except Exception as e:
            logger.error("mouse_move_failed", error=str(e))
            raise
    
    def mouse_click(self, x: int | None = None, y: int | None = None, button: str = "left", clicks: int = 1) -> dict[str, Any]:
        logger.info("mouse_click", x=x, y=y, button=button, clicks=clicks)
        
        try:
            if x is not None and y is not None:
                pyautogui.click(x, y, clicks=clicks, button=button)
            else:
                pyautogui.click(clicks=clicks, button=button)
            
            logger.info("mouse_clicked", x=x, y=y, button=button, clicks=clicks)
            return {
                "success": True,
                "action": "mouse_click",
                "x": x,
                "y": y,
                "button": button,
                "clicks": clicks,
            }
        
        except Exception as e:
            logger.error("mouse_click_failed", error=str(e))
            raise
    
    def keyboard_type(self, text: str, interval: float | None = None) -> dict[str, Any]:
        logger.info("keyboard_type", text_length=len(text), interval=interval)
        
        try:
            interval = interval or self.config.COMPUTER_USE_TYPING_INTERVAL
            pyautogui.write(text, interval=interval)
            
            logger.info("keyboard_typed", text_length=len(text))
            return {
                "success": True,
                "action": "keyboard_type",
                "text_length": len(text),
            }
        
        except Exception as e:
            logger.error("keyboard_type_failed", error=str(e))
            raise
    
    def keyboard_press(self, key: str, presses: int = 1) -> dict[str, Any]:
        logger.info("keyboard_press", key=key, presses=presses)
        
        try:
            for _ in range(presses):
                pyautogui.press(key)
            
            logger.info("keyboard_pressed", key=key, presses=presses)
            return {
                "success": True,
                "action": "keyboard_press",
                "key": key,
                "presses": presses,
            }
        
        except Exception as e:
            logger.error("keyboard_press_failed", error=str(e))
            raise
    
    def keyboard_hotkey(self, *keys: str) -> dict[str, Any]:
        logger.info("keyboard_hotkey", keys=keys)
        
        try:
            pyautogui.hotkey(*keys)
            
            logger.info("keyboard_hotkey_pressed", keys=keys)
            return {
                "success": True,
                "action": "keyboard_hotkey",
                "keys": list(keys),
            }
        
        except Exception as e:
            logger.error("keyboard_hotkey_failed", error=str(e))
            raise
    
    def get_screen_size(self) -> dict[str, Any]:
        try:
            width, height = pyautogui.size()
            
            return {
                "width": width,
                "height": height,
            }
        
        except Exception as e:
            logger.error("get_screen_size_failed", error=str(e))
            raise
    
    def get_mouse_position(self) -> dict[str, Any]:
        try:
            x, y = pyautogui.position()
            
            return {
                "x": x,
                "y": y,
            }
        
        except Exception as e:
            logger.error("get_mouse_position_failed", error=str(e))
            raise
    
    def locate_on_screen(self, image_path: str, confidence: float | None = None) -> dict[str, Any]:
        logger.info("locate_on_screen", image_path=image_path, confidence=confidence)
        
        try:
            confidence = confidence or self.config.COMPUTER_USE_LOCATE_CONFIDENCE
            location = pyautogui.locateOnScreen(image_path, confidence=confidence)
            
            if location:
                logger.info("image_located", location=location)
                return {
                    "success": True,
                    "found": True,
                    "x": location.left,
                    "y": location.top,
                    "width": location.width,
                    "height": location.height,
                }
            else:
                logger.info("image_not_found", image_path=image_path)
                return {
                    "success": True,
                    "found": False,
                }
        
        except Exception as e:
            logger.error("locate_on_screen_failed", error=str(e))
            raise
