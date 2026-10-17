#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2026/10/16 10:30
@Author  : thezehui@gmail.com
@File    : validator.py
"""
import re

from wtforms.validators import URL

# 内置图标（ui/public/app-icons 下的静态资源）以相对路径形式存储
BUILTIN_ICON_PATTERN = re.compile(r"^/app-icons/[A-Za-z0-9_-]+\.svg$")


class BuiltinIconValidator(URL):
    """图标校验器：兼容完整图片URL与内置图标相对路径"""

    def __call__(self, form, field):
        # 1.内置图标使用相对路径，跳过标准URL校验
        if isinstance(field.data, str) and BUILTIN_ICON_PATTERN.match(field.data):
            return

        # 2.其余情况仍按标准URL校验
        super().__call__(form, field)
