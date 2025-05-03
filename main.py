import os
import win32gui
import win32con
import pyautogui
import time
import cv2
import numpy as np
import yaml
import keyboard
from threading import Thread
from enum import Enum, auto
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass
from setting import Config
import logging


class FishState(Enum):
    """钓鱼游戏的状态枚举"""
    START_FISHING = auto()  # 开始钓鱼
    CAST_ROD = auto()       # 抛竿
    NO_BAIT = auto()        # 鱼饵不足
    CATCH_FISH = auto()     # 捕鱼
    FISHING = auto()        # 钓鱼中
    INSTANT_KILL = auto()   # 秒杀
    END_FISHING = auto()    # 结束钓鱼
    EXIT = auto()           # 退出


@dataclass
class GameConfig:
    """游戏配置数据类"""
    window_title: str  # 模拟器窗口标题
    window_size: Tuple[int, int, int, int]  # 模拟器窗口大小和位置 (x, y, width, height)
    start_fishing_pos: Optional[Tuple[int, int]] = None  # 开始钓鱼按钮的中心点坐标
    rod_position: Optional[Tuple[int, int]] = None  # 钓鱼界面拉杆位置中心点坐标
    pressure_indicator_pos: Optional[Tuple[int, int]] = None  # 用来判断压力是否过高的点的位置
    low_pressure_color: Optional[Tuple[int, int, int]] = None  # 用来判断压力是否过高的点的颜色
    original_rod_color: Optional[Tuple[int, int, int]] = None  # 钓鱼界面拉杆位置中心点颜色
    direction_icon_positions: Optional[Dict[str, Tuple[int, int]]] = None  # 方向图标位置字典
    retry_button_center: Optional[Tuple[int, int]] = None  # 再来一次按钮的中心点坐标
    use_bait_button_pos: Optional[Tuple[int, int]] = None  # 使用鱼饵按钮的位置


class WindowManager:
    """窗口管理类，处理窗口相关的操作"""
    
    @staticmethod
    def find_window(title: str) -> int:
        """查找指定标题的窗口句柄"""
        return win32gui.FindWindow(None, title)
    
    @staticmethod
    def get_window_rect(hwnd: int) -> Tuple[int, int, int, int]:
        """获取窗口位置和大小"""
        return win32gui.GetWindowRect(hwnd)
    
    @staticmethod
    def bring_to_front(hwnd: int) -> None:
        """将窗口置于最前端并激活"""
        win32gui.SetForegroundWindow(hwnd)
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    
    @staticmethod
    def handle_window(config: GameConfig) -> None:
        """处理窗口配置和位置"""
        hwnd = WindowManager.find_window(config.window_title)
        if not hwnd:
            raise ValueError(f"未找到标题为 {config.window_title} 的窗口")
        
        WindowManager.bring_to_front(hwnd)
        win32gui.SetWindowPos(hwnd, None, *config.window_size, 0)
        time.sleep(0.5)

class ImageProcessor:
    """图像处理类，处理所有图像相关的操作"""
    
    @staticmethod
    def get_screenshot(size: Tuple[int, int, int, int], 
                      is_save: bool = False, 
                      save_path: Optional[str] = None) -> np.ndarray:
        """获取屏幕截图"""
        img = pyautogui.screenshot(region=size)
        img_np = np.array(img)
        img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        if is_save and save_path:
            img.save(save_path)
        return img_np
    
    @staticmethod
    def is_match_template(img: np.ndarray, 
                         template: np.ndarray, 
                         threshold: float = 0.8) -> bool:
        """模板匹配判断"""
        res = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= threshold)
        return len(loc[0]) > 0
    
    @staticmethod
    def match_template(img: np.ndarray, 
                      template: np.ndarray, 
                      threshold: float = 0.8,
                      position: Tuple[float, float] = (0.5, 0.5)) -> Tuple[int, int]:
        """模板匹配并返回指定位置
        
        Args:
            img: 输入图像
            template: 模板图像
            threshold: 匹配阈值
            position: 归一化位置坐标，范围[0,1]，(0,0)表示左上角，(1,1)表示右下角，默认为(0.5,0.5)即中心位置
                    如果值超出范围，将自动调整到最近的合法值
            
        Returns:
            返回指定位置的坐标 (x, y)
        """
        # 将position值限制在[0,1]范围内
        clamped_x = max(0, min(1, position[0]))
        clamped_y = max(0, min(1, position[1]))
        
        # 如果值被调整，记录日志
        if clamped_x != position[0] or clamped_y != position[1]:
            logging.warning(f"position参数值被调整: {position} -> ({clamped_x}, {clamped_y})")
            
        res = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
        
        # 获取模板的宽高
        template_width = template.shape[1]
        template_height = template.shape[0]
        
        # 根据归一化位置计算实际坐标
        x = int(max_loc[0] + template_width * clamped_x)
        y = int(max_loc[1] + template_height * clamped_y)
            
        return (x, y)


class ConfigManager:
    """配置管理类，处理配置文件的读写"""
    
    @staticmethod
    def write_yaml(data: Dict[str, Any]) -> None:
        """写入YAML配置文件"""
        with open(str(Config.CONFIG_FILE), 'w', encoding='utf-8') as f:
            yaml.dump(data, f)
    
    @staticmethod
    def read_yaml() -> Dict[str, Any]:
        """读取YAML配置文件"""
        with open(str(Config.CONFIG_FILE), 'r', encoding='utf-8') as f:
            return yaml.load(f, Loader=yaml.FullLoader)


class MouseController:
    """鼠标控制类，处理所有鼠标操作"""
    
    @staticmethod
    def press_mouse_move(start_x: int, start_y: int, 
                        x: int, y: int, button: str = 'left') -> None:
        """模拟鼠标拖拽操作"""
        pyautogui.mouseDown(start_x, start_y, button=button)
        pyautogui.moveTo(start_x + x, start_y + y, duration=0.03)
        pyautogui.mouseUp(button=button)
    
    @staticmethod
    def click(position: Tuple[int, int]) -> None:
        """点击指定位置"""
        pyautogui.click(position)


class FishingStateManager:
    """负责状态管理和转换的类"""

    def __init__(self):
        self.ui_recognizer = FishingUIRecognizer()
        self.current_state = FishState.START_FISHING
        self._setup_state_flags()
    
    def _setup_state_flags(self) -> None:
        """初始化状态标志"""
        self.first_start_fishing = True
        self.first_cast_rod = True
        self.first_no_bait = True
        self.first_retry = True
        self.first_instant_kill = True
        self.rod_retrieve_time = 0
    
    def update_state(self, current_img: np.ndarray) -> None:
        """更新当前状态"""
        old_state = self.current_state
        
        match self.current_state:
            case FishState.START_FISHING:
                if self.ui_recognizer.check_cast_rod_ui(current_img):
                    self.current_state = FishState.CAST_ROD
            
            case FishState.CAST_ROD:
                if self.ui_recognizer.check_no_bait_ui(current_img):
                    self.current_state = FishState.NO_BAIT
                elif self.ui_recognizer.check_catch_fish_ui(current_img):
                    self.current_state = FishState.CATCH_FISH
            
            case FishState.NO_BAIT:
                if not self.ui_recognizer.check_no_bait_ui(current_img):
                    self.current_state = FishState.CAST_ROD
            
            case FishState.CATCH_FISH:
                if self.ui_recognizer.check_fishing_ui(current_img):
                    # FISHING 页面已就绪，但有些元素状态重置需要时间，比如挥杆
                    time.sleep(2)
                    self.current_state = FishState.FISHING
            
            case FishState.FISHING:
                if self.ui_recognizer.check_end_fishing_ui(current_img):
                    self.current_state = FishState.END_FISHING
                elif self.ui_recognizer.check_instant_kill_ui(current_img):
                    self.current_state = FishState.INSTANT_KILL

            case FishState.INSTANT_KILL:
                if self.ui_recognizer.check_end_fishing_ui(current_img):
                    self.current_state = FishState.END_FISHING
            
            case FishState.END_FISHING:
                if self.ui_recognizer.check_cast_rod_ui(current_img):
                    self.current_state = FishState.CAST_ROD
        
        if old_state != self.current_state:
            logging.info(f"页面状态变化: {old_state} -> {self.current_state}")
    
    def reset_state_flags(self) -> None:
        """重置所有状态标志"""
        self._setup_state_flags()

class FishingPositionDetector:
    """负责位置检测的类"""
    
    def __init__(self, config: GameConfig):
        self.config = config
    
    def detect_start_fishing_pos(self) -> None:
        """检测开始钓鱼按钮位置"""
        start_fishing_UI_img = ImageProcessor.get_screenshot(self.config.window_size)
        start_fishing_button_img = cv2.imread(str(Config.START_FISH_BUTTON))
        pos = ImageProcessor.match_template(start_fishing_UI_img, start_fishing_button_img)
        self.config.start_fishing_pos = (
            pos[0] + self.config.window_size[0],
            pos[1] + self.config.window_size[1]
        )
        ConfigManager.write_yaml(self.config.__dict__)
    
    def detect_fishing_positions(self) -> None:
        """检测钓鱼相关位置"""
        fishing_img = ImageProcessor.get_screenshot(self.config.window_size)
        push_rod_icon = cv2.imread(str(Config.PUSH_ROD_BUTTON))
        pressure_img = cv2.imread(str(Config.PRESSURE_IMAGE))
        
        rod_pos = ImageProcessor.match_template(fishing_img, push_rod_icon)
        pressure_pos = ImageProcessor.match_template(fishing_img, pressure_img, position=(0.25, 0.5))
        
        self.config.rod_position = (
            rod_pos[0] + self.config.window_size[0],
            rod_pos[1] + self.config.window_size[1]
        )
        self.config.pressure_indicator_pos = (
            pressure_pos[0] + self.config.window_size[0],
            pressure_pos[1] + self.config.window_size[1]
        )
        
        self.config.low_pressure_color = pyautogui.pixel(*self.config.pressure_indicator_pos)
        self.config.original_rod_color = pyautogui.pixel(*self.config.rod_position)
        
        ConfigManager.write_yaml(self.config.__dict__)
    
    def detect_use_button_pos(self) -> None:
        """检测使用按钮位置"""
        bait_ui_img = ImageProcessor.get_screenshot(self.config.window_size)
        use_button_img = cv2.imread(str(Config.USE_BUTTON))
        pos = ImageProcessor.match_template(bait_ui_img, use_button_img)
        self.config.use_bait_button_pos = (
            pos[0] + self.config.window_size[0],
            pos[1] + self.config.window_size[1]
        )
        ConfigManager.write_yaml(self.config.__dict__)
    
    def detect_retry_button_pos(self) -> None:
        """检测再次钓鱼按钮位置"""
        game_over_img = ImageProcessor.get_screenshot(self.config.window_size)
        retry_icon = cv2.imread(str(Config.RETRY_BUTTON))
        pos = ImageProcessor.match_template(game_over_img, retry_icon)
        self.config.retry_button_center = (
            pos[0] + self.config.window_size[0],
            pos[1] + self.config.window_size[1]
        )
        ConfigManager.write_yaml(self.config.__dict__)
    
    def detect_direction_icons(self) -> None:
        """检测方向图标位置"""
        bottom_half_size = (
            self.config.window_size[0],
            (self.config.window_size[1] + self.config.window_size[3]) // 2,
            self.config.window_size[2],
            (self.config.window_size[1] + self.config.window_size[3]) // 2
        )
        bottom_half_img = ImageProcessor.get_screenshot(bottom_half_size)
        
        self.config.direction_icon_positions = {}
        for dir_icon_path in Config.DIRECTION_ICONS:
            dir_icon = cv2.imread(str(dir_icon_path))
            pos = ImageProcessor.match_template(bottom_half_img, dir_icon)
            name = dir_icon_path.stem
            self.config.direction_icon_positions[name] = (
                pos[0] + bottom_half_size[0],
                pos[1] + bottom_half_size[1]
            )
        
        ConfigManager.write_yaml(self.config.__dict__)


class FishingActionExecutor:
    """负责执行具体的钓鱼动作的类"""
    
    def __init__(self, config: GameConfig):
        self.config = config
        self.fishing_click_time = 0
        self.rod_retrieve_time = 0
    
    def handle_default_state(self) -> None:
        """处理默认状态"""
        MouseController.click(self.config.start_fishing_pos)
    
    def handle_cast_rod_state(self) -> None:
        """处理抛竿状态"""
        MouseController.press_mouse_move(
            self.config.start_fishing_pos[0],
            self.config.start_fishing_pos[1],
            0, -100
        )
    
    def handle_no_bait_state(self) -> None:
        """处理鱼饵不足状态"""
        MouseController.click(self.config.use_bait_button_pos)
    
    def handle_catch_fish_state(self) -> None:
        """处理捕鱼状态"""
        click_interval = Config.FISHING_CLICK_INTERVAL * 3
        current_time = time.time()
        if current_time - self.fishing_click_time >= click_interval:
            MouseController.click(self.config.start_fishing_pos)
            self.fishing_click_time = current_time
    
    def handle_ongoing_fishing(self) -> None:
        """处理持续钓鱼状态"""
        current_time = time.time()
        click_interval = Config.FISHING_CLICK_INTERVAL
        pressure_check_interval = click_interval * 3

        # 检查收杆
        if current_time - self.rod_retrieve_time > Config.ROD_RETRIEVE_INTERVAL:
            self.handle_rod_retrieve()

        # 检查点击操作
        if current_time - self.fishing_click_time >= click_interval:
            current_pressure_color = pyautogui.pixel(*self.config.pressure_indicator_pos)
            # 压力条颜色改变, 增加点击保护间隔
            if current_pressure_color != self.config.low_pressure_color:
                self.fishing_click_time = current_time + pressure_check_interval
            # 压力条颜色未改变, 点击收杆
            else:
                MouseController.click(self.config.start_fishing_pos) 
                self.fishing_click_time = current_time

        # 拉竿检查
        current_rod_color = pyautogui.pixel(*self.config.rod_position)
        if current_rod_color != self.config.original_rod_color:
            self.handle_rod_movement()
    
    def handle_rod_movement(self) -> None:
        """处理拉杆移动"""
        MouseController.press_mouse_move(
            self.config.rod_position[0],
            self.config.rod_position[1],
            100, 0
        )
        MouseController.press_mouse_move(
            self.config.rod_position[0],
            self.config.rod_position[1],
            -100, 0
        )
    
    def handle_rod_retrieve(self) -> None:
        """处理收杆"""
        MouseController.press_mouse_move(
            self.config.start_fishing_pos[0],
            self.config.start_fishing_pos[1],
            0, -75
        )
        self.rod_retrieve_time = time.time()
    
    def handle_end_fishing_state(self) -> None:
        """处理结束钓鱼状态"""
        MouseController.click(self.config.retry_button_center)
    
    def handle_direction_sequence(self) -> None:
        """处理方向序列"""
        top_half_size = (
            self.config.window_size[0],
            self.config.window_size[1],
            self.config.window_size[2],
            (self.config.window_size[3] + self.config.window_size[1]) // 2
        )
        top_half_img = ImageProcessor.get_screenshot(top_half_size)
        
        all_icons_dict = {}
        for dir_icon_path in Config.DIRECTION_ICONS:
            dir_icon = cv2.imread(str(dir_icon_path))
            res = cv2.matchTemplate(top_half_img, dir_icon, cv2.TM_CCOEFF_NORMED)
            res_loc = np.where(res >= 0.8)
            if len(res_loc[0]) > 0:
                points = list(zip(*res_loc[::-1]))
                classified_points = self._classify_positions(points)
                for point in classified_points:
                    all_icons_dict[point] = dir_icon_path.stem
        
        # 按x坐标排序
        all_icons_list = sorted(all_icons_dict.items(), key=lambda x: x[0][0])
        for pos, name in all_icons_list:
            logging.info(f"{name}, 位置: {pos}")
            click_pos = self.config.direction_icon_positions[name]
            MouseController.click(click_pos)
    
    @staticmethod
    def _classify_positions(point_list: list) -> list:
        """对识别出来的所有位置进行分类"""
        result_points = []
        for i in range(len(point_list)):
            point_set = set()
            if point_list[i] is None:
                continue
            point_set.add(point_list[i])
            for j in range(i + 1, len(point_list)):
                if point_list[j] is None:
                    continue
                if (abs(point_list[i][0] - point_list[j][0]) < 10 and 
                    abs(point_list[i][1] - point_list[j][1]) < 10):
                    point_set.add(point_list[j])
                    point_list[j] = None
            if len(point_set) > 1:
                average_x = int(sum([x[0] for x in point_set]) / len(point_set))
                average_y = int(sum([x[1] for x in point_set]) / len(point_set))
                result_points.append((average_x, average_y))
        return result_points


class FishingUIRecognizer:
    """负责UI识别的类"""
    
    def check_start_fishing_ui(self, img: np.ndarray) -> bool:
        """检查开始钓鱼界面"""
        start_button = cv2.imread(str(Config.START_FISH_BUTTON))
        return ImageProcessor.is_match_template(img, start_button)
    
    def check_cast_rod_ui(self, img: np.ndarray) -> bool:
        """检查抛竿界面"""
        huaner = cv2.imread(str(Config.BAIT_IMAGE))
        return ImageProcessor.is_match_template(img, huaner)
    
    def check_no_bait_ui(self, img: np.ndarray) -> bool:
        """检查鱼饵不足界面"""
        use_button = cv2.imread(str(Config.USE_BUTTON))
        return ImageProcessor.is_match_template(img, use_button)
    
    def check_catch_fish_ui(self, img: np.ndarray) -> bool:
        """检查捕鱼界面"""
        time_icon = cv2.imread(str(Config.TIME_IMAGE))
        return ImageProcessor.is_match_template(img, time_icon)
    
    def check_fishing_ui(self, img: np.ndarray) -> bool:
        """检查钓鱼界面"""
        pressure_img = cv2.imread(str(Config.PRESSURE_IMAGE))
        return ImageProcessor.is_match_template(img, pressure_img)
    
    def check_instant_kill_ui(self, img: np.ndarray) -> bool:
        """检查秒杀界面"""
        up_button = cv2.imread(str(Config.UP_IMAGE))
        return ImageProcessor.is_match_template(img, up_button)
    
    def check_end_fishing_ui(self, img: np.ndarray) -> bool:
        """检查结束钓鱼界面"""
        retry_button = cv2.imread(str(Config.RETRY_BUTTON))
        return ImageProcessor.is_match_template(img, retry_button)


class FishingGame:
    """钓鱼游戏主类"""
    
    def __init__(self):
        self.config = self._load_config()
        self.position_detector = FishingPositionDetector(self.config)
        self.action_executor = FishingActionExecutor(self.config)
        self.state_manager = FishingStateManager()
    
    def _load_config(self) -> GameConfig:
        """加载游戏配置"""
        if not Config.CONFIG_FILE.exists():
            config_dict = {}
        else:
            config_dict = ConfigManager.read_yaml()
        
        # 设置默认窗口标题
        if 'window_title' not in config_dict:
            config_dict['window_title'] = Config.WINDOW_TITLE
            ConfigManager.write_yaml(config_dict)
        
        # 设置窗口大小
        config_dict['window_size'] = Config.WINDOW_SIZE
        
        return GameConfig(**config_dict)
    
    def check_current_UI(self) -> None:
        """检查当前游戏界面状态"""
        # 设置全局退出标志
        self.should_exit = False
        
        # 添加热键监听器
        keyboard.add_hotkey('esc', lambda: setattr(self, 'should_exit', True))
        
        while not self.should_exit:
            current_img = ImageProcessor.get_screenshot(self.config.window_size)
            self.state_manager.update_state(current_img)
        
        # 清理热键监听器
        keyboard.remove_hotkey('esc')
        self.state_manager.current_state = FishState.EXIT
    
    def _handle_state(self) -> None:
        """处理当前状态"""
        match self.state_manager.current_state:
            case FishState.START_FISHING if self.state_manager.first_start_fishing:
                if not self.config.start_fishing_pos:
                    self.position_detector.detect_start_fishing_pos()
                self.action_executor.handle_default_state()
                self.state_manager.first_start_fishing = False
            
            case FishState.CAST_ROD if self.state_manager.first_cast_rod:
                self.action_executor.handle_cast_rod_state()
                self.state_manager.first_cast_rod = False
                self.state_manager.first_retry = True
            
            case FishState.NO_BAIT if self.state_manager.first_no_bait:
                if not self.config.use_bait_button_pos:
                    self.position_detector.detect_use_button_pos()
                self.action_executor.handle_no_bait_state()
                self.state_manager.first_no_bait = False
                self.state_manager.first_cast_rod = True
            
            case FishState.CATCH_FISH:
                self.action_executor.handle_catch_fish_state()
            
            case FishState.FISHING:
                if not self.config.rod_position or not self.config.pressure_indicator_pos:
                    self.position_detector.detect_fishing_positions()
                self.action_executor.handle_ongoing_fishing()
            
            case FishState.END_FISHING if self.state_manager.first_retry:
                if not self.config.retry_button_center:
                    self.position_detector.detect_retry_button_pos()
                self.action_executor.handle_end_fishing_state()
                self.state_manager.reset_state_flags()
                self.state_manager.first_retry = False
            
            case FishState.INSTANT_KILL if self.state_manager.first_instant_kill:
                if not self.config.direction_icon_positions:
                    self.position_detector.detect_direction_icons()
                self.action_executor.handle_direction_sequence()
                self.state_manager.first_instant_kill = False

    def run(self) -> None:
        """运行游戏主循环"""
        try:
            pyautogui.PAUSE = Config.FISHING_CLICK_INTERVAL / 2
            WindowManager.handle_window(self.config)
            state_check_thread = Thread(target=self.check_current_UI)
            state_check_thread.start()
            
            while self.state_manager.current_state != FishState.EXIT:
                self._handle_state()
            
            ConfigManager.write_yaml(self.config.__dict__)
            logging.info("游戏结束")
            
        except Exception as e:
            logging.error(f"游戏运行出错: {str(e)}")
            raise


def main():
    """主函数"""
    try:
        game = FishingGame()
        game.run()
    except Exception as e:
        logging.error(f"程序运行出错: {str(e)}")
        raise


if __name__ == '__main__':
    main()
