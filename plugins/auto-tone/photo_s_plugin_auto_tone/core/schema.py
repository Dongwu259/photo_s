"""JSON Schema 定义（input/output contract）"""

INPUT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "AutoToneInput",
    "type": "object",
    "properties": {
        "image_path": {"type": "string", "description": "图像绝对路径"},
        "strength": {
            "type": "number",
            "default": 1.0,
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "调色强度 0=原图 1=完全采用模型预测",
        },
        "render": {
            "type": "boolean",
            "default": True,
            "description": "是否渲染输出图",
        },
        "use_rag": {
            "type": "boolean",
            "default": True,
            "description": "是否启用 RAG 检索增强",
        },
        "use_advisor": {
            "type": "boolean",
            "default": False,
            "description": "低置信度时启用 advisor 修正",
        },
        "output_path": {
            "type": ["string", "null"],
            "default": None,
            "description": "自定义输出路径",
        },
    },
    "required": ["image_path"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "AutoToneOutput",
    "type": "object",
    "properties": {
        "schema_version": {"type": "integer", "const": 1},
        "options": {
            "type": "object",
            "description": "9 字段调整参数",
            "properties": {
                "exposure": {"type": "number"},
                "contrast": {"type": "number"},
                "saturation": {"type": "number"},
                "vibrance": {"type": "number"},
                "wb_temp": {"type": "number"},
                "wb_tint": {"type": "number"},
                "clarity": {"type": "number"},
                "texture": {"type": "number"},
                "dehaze": {"type": "number"},
            },
            "required": ["exposure", "contrast", "saturation"],
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "0-1 置信度，<0.4 建议人工复审",
        },
        "warnings": {
            "type": "array",
            "items": {"type": "string"},
            "description": "提示信息列表",
        },
        "rendered_path": {
            "type": ["string", "null"],
            "description": "渲染图保存路径，render=False 时为 null",
        },
        "metadata": {
            "type": "object",
            "properties": {
                "psnr_estimate": {"type": "number"},
                "rag_used": {"type": "boolean"},
                "anomaly_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "model_version": {"type": "string"},
                "duration_ms": {"type": "number"},
            },
        },
    },
    "required": ["schema_version", "options", "confidence", "warnings"],
}