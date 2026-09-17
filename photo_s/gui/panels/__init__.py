"""GUI 面板 mixin（v2.6 结构项：app.py 拆分启动）。

PhotoSApp 以多继承组合各面板簇；mixin 不定义 __init__、不持有独立
状态，全部经 self 使用宿主的属性与方法（运行期晚绑定）。
"""

from .review import ReviewPanelMixin
from .settings import SettingsPanelMixin
from .mask import MaskPanelMixin
from .dialogs import WorkflowDialogsMixin
from .watch import WatchPanelMixin

__all__ = ["ReviewPanelMixin", "WorkflowDialogsMixin",
           "WatchPanelMixin", "SettingsPanelMixin", "MaskPanelMixin"]
