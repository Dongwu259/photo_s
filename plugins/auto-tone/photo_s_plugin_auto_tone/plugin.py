"""Plugin 钩子实现（photo_s.plugins entry-point）"""
import os
from typing import List, Optional

from photo_s.hooks import PhotoSPlugin, PluginContext
from photo_s.modelstore import WeightSpec

from . import models


class AutoTonePlugin(PhotoSPlugin):
    """photo-s 插件：AI 自动调色

    注册方式（pyproject.toml）：
        [project.entry-points."photo_s.plugins"]
        auto_tone = "photo_s_plugin_auto_tone:AutoTonePlugin"
    """

    name = "auto_tone"

    provides = ("auto_tone",)

    def register_mcp_tools(self, mcp) -> None:
        """v2.3 wiring: photo-s mcp 启动时调用（hooks.PhotoSPlugin 协议）。"""
        from .api.mcp_tools import register_mcp_tools
        register_mcp_tools(mcp)

    def register_rest(self, handler_class) -> None:
        """v2.3 wiring: photo-s serve 启动时调用（hooks.PhotoSPlugin 协议）。"""
        from .api.rest import register_routes
        register_routes(handler_class)

    def weight_specs(self) -> List[WeightSpec]:
        return models.weight_specs()

    def auto_tone(
        self,
        img,
        strength: float = 1.0,
        ctx: Optional[PluginContext] = None,
    ):
        """在 photo_s 引擎中调用：返回调整后的 PIL.Image

        Args:
            img: PIL.Image
            strength: 调色强度 0-1
            ctx: PluginContext（包含 input_path, output_path 等）
        """
        from PIL import Image

        from .core.pipeline import run_auto_tone
        from .core.render import render_options

        input_path = ctx.input_path if ctx else None
        if not input_path:
            return img

        result = run_auto_tone(
            image_path=input_path,
            strength=strength,
            render=False,  # 渲染由本方法完成并返回 PIL Image
            use_rag=True,
            use_advisor=False,
        )

        options = result.get("options", {})
        if not options:
            return img

        import tempfile
        # Always render through JPEG: the temp file only ferries pixels back
        # into a PIL Image (the engine re-saves in the target format). A RAW
        # input suffix (.cr2/.nef/...) used to be kept and PIL cannot WRITE
        # RAW — every RAW input died with "unknown file extension".
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            tmp_path = f.name
        try:
            render_options(img, options, tmp_path, strength=1.0)
            return Image.open(tmp_path).copy()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
